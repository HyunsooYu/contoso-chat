"""가계 원장 시뮬레이터 - 동일소비 정규화.

**왜 점수가 아니라 이 방식인가 (초안 결함 A-3)**

"전세 81점 vs 매수 68점"에서 13점 차이는 아무 의미가 없다. 가중치를 5%만 바꾸면
순위가 뒤집히는데 그 가중치의 근거를 댈 방법이 없기 때문이다.

대신 이렇게 한다:
  모든 옵션에 **같은 소득과 같은 생활비**를 주고, 주거 관련 현금흐름만 다르게 한 뒤,
  종료 시점의 **세후 순자산**을 비교한다.

이 방식의 이점:
  - 원금상환 vs 이자 구분이 자동으로 맞는다 (원금은 순자산에 남으므로)
  - 보증금 회수가 자동으로 맞는다 (자산 이동일 뿐 비용이 아니므로)
  - 유동성 부족이 자동으로 드러난다 (현금이 마이너스가 되면 페널티 차입 발생)
  - 결과 단위가 '원'이라 "4,200만원 유리" 처럼 말할 수 있다
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.budget import LivingCostPath, evaluate_budget
from fde.models import FamilyState
from fde.money import monthly_rate, npv
from fde.options import Path, Schedule
from fde.policy import PolicySet
from fde.tax import net_sale_proceeds


@dataclass
class LedgerMonth:
    t: int
    income: float
    living: float
    housing_consumption: float
    housing_principal: float
    housing_one_off: float
    housing_lump: float
    deposit_delta: float
    savings: float
    liquid: float
    penalty_debt: float
    net_worth: float


@dataclass
class SimResult:
    name: str
    feasible: bool
    infeasible_reason: str = ""

    terminal_net_worth: float = 0.0
    npv_housing_cost: float = 0.0        # 소비성 주거비만의 현재가치 (설명용)
    total_interest_paid: float = 0.0
    total_one_off: float = 0.0

    min_liquid: float = 0.0
    liquidity_breach_months: int = 0
    went_negative: bool = False
    peak_penalty_debt: float = 0.0

    max_housing_burden: float = 0.0
    max_total_payment_ratio: float = 0.0
    burden_breach_months: int = 0

    nonmonetary_monthly: float = 0.0     # 통근/육아/학군 WTP 월 환산
    nonmonetary_npv: float = 0.0

    adjusted_net_worth: float = 0.0      # 순자산 + 비화폐 편익 NPV

    ledger: list[LedgerMonth] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def nonmonetary_monthly_value(state: FamilyState, schedule: Schedule) -> tuple[float, list[str]]:
    """화폐화 가능한 비금전 편익을 월 원 단위로 환산.

    가중치를 지어내지 않는다. 사용자가 답한 지불의사(WTP)만 쓴다.
    preferences 가 비어 있으면 0 이 되고, 리포트가 그 사실을 경고한다.
    """
    p = state.preferences
    c = schedule.spec.candidate
    baseline = state.candidates[0] if state.candidates else c

    notes: list[str] = []
    total = 0.0

    dc = baseline.total_daily_commute_minutes() - c.total_daily_commute_minutes()
    if p.krw_per_commute_minute_month and dc:
        v = dc * p.krw_per_commute_minute_month
        total += v
        notes.append(f"통근 {dc:+d}분/일 -> {v:+,.0f}원/월")

    dd = baseline.daycare_minutes - c.daycare_minutes
    if p.krw_per_daycare_minute_month and dd:
        v = dd * p.krw_per_daycare_minute_month
        total += v
        notes.append(f"어린이집 {dd:+d}분 -> {v:+,.0f}원/월")

    dg = baseline.grandparents_minutes - c.grandparents_minutes
    if p.krw_per_grandparent_minute_month and dg:
        v = dg * p.krw_per_grandparent_minute_month
        total += v
        notes.append(f"조부모 거리 {dg:+d}분 -> {v:+,.0f}원/월")

    ds = c.school_score - baseline.school_score
    if p.school_quality_wtp_monthly and ds:
        v = ds * p.school_quality_wtp_monthly
        total += v
        notes.append(f"학군 {ds:+.2f} -> {v:+,.0f}원/월")

    dsat = c.satisfaction_score - baseline.satisfaction_score
    if p.satisfaction_wtp_monthly and dsat:
        v = dsat * p.satisfaction_wtp_monthly
        total += v
        notes.append(f"주거만족 {dsat:+.2f} -> {v:+,.0f}원/월")

    return total, notes


def simulate(
    state: FamilyState,
    policy: PolicySet,
    schedule: Schedule,
    path: Path,
    living: LivingCostPath,
    horizon: int,
) -> SimResult:
    if not schedule.feasible:
        return SimResult(
            schedule.spec.name, feasible=False,
            infeasible_reason=schedule.infeasible_reason, notes=schedule.notes,
        )

    a = state.assumptions
    res = SimResult(schedule.spec.name, feasible=True, notes=list(schedule.notes))

    liquid = state.liquid_assets()
    illiquid = sum(x.amount for x in state.assets if not x.is_liquid)
    illiquid_r = monthly_rate(a.portfolio_return, "effective")
    penalty_debt = 0.0
    penalty_r = monthly_rate(a.penalty_borrow_rate)

    emergency_floor = living.at(0) * state.preferences.min_emergency_months

    by_t = {m.t: m for m in schedule.months}
    cost_flows: list[float] = []
    disc = monthly_rate(a.discount_rate, "effective")

    base_income = state.family.household_monthly_income()
    annual_bonus = sum(p.annual_bonus for p in state.family.adults)

    res.min_liquid = liquid

    for t in range(horizon):
        hm = by_t.get(t)
        if hm is None:
            continue

        income = base_income * path.income[t] * (1.0 + a.income_growth) ** (t / 12.0)
        if t % 12 == 11:
            income += annual_bonus * (1.0 + a.income_growth) ** (t / 12.0)

        cost = living.at(t)
        h_cons = hm.consumption_out
        h_prin = hm.principal_out
        h_once = hm.one_off_out
        # lump_out(기존 대출 일시상환)은 현금흐름에는 잡히지만
        # 비용도 아니고 월 부담률도 아니다. 잔액 이동일 뿐이다.

        cash_out = hm.cash_out
        savings = income - cost - cash_out

        # 포트폴리오 수익은 기초잔액에 적용
        liquid = liquid * (1.0 + path.portfolio[t]) + savings

        # 유동성 부족 -> 페널티 차입 (신용대출)
        penalty_debt *= 1.0 + penalty_r
        if liquid < 0:
            penalty_debt += -liquid
            liquid = 0.0
            res.went_negative = True
        elif penalty_debt > 0:
            repay = min(liquid, penalty_debt)
            liquid -= repay
            penalty_debt -= repay

        illiquid *= 1.0 + illiquid_r

        if liquid < emergency_floor:
            res.liquidity_breach_months += 1
        res.min_liquid = min(res.min_liquid, liquid)
        res.peak_penalty_debt = max(res.peak_penalty_debt, penalty_debt)

        # 부담률 (일회성 비용은 제외 - 월 부담이 아니므로)
        if income > 0:
            burden = h_cons / income
            total_ratio = (h_cons + h_prin) / income
            res.max_housing_burden = max(res.max_housing_burden, burden)
            res.max_total_payment_ratio = max(res.max_total_payment_ratio, total_ratio)
            if (
                burden > state.preferences.max_housing_burden_ratio
                or total_ratio > state.preferences.max_total_payment_ratio
            ):
                res.burden_breach_months += 1

        res.total_interest_paid += h_cons
        res.total_one_off += h_once
        cost_flows.append(h_cons + h_once)

        nw = liquid + illiquid + hm.deposit_balance + hm.home_value - hm.debt_balance - penalty_debt
        res.ledger.append(
            LedgerMonth(t, income, cost, h_cons, h_prin, h_once, hm.lump_out,
                        hm.deposit_delta, savings, liquid, penalty_debt, nw)
        )

    # ---- 종료시점 청산 (세후) ------------------------------------
    last = schedule.months[-1] if schedule.months else None
    terminal = liquid + illiquid - penalty_debt
    if last:
        terminal += last.deposit_balance
        terminal -= last.debt_balance
        if last.home_value > 0:
            org = schedule.origination
            hold = horizon - _decision_month(schedule)
            sale = net_sale_proceeds(
                sale_price=last.home_value,
                purchase_price=org.get("price", 0.0),
                acquisition_cost=org.get("one_off", 0.0),
                hold_months=hold,
                live_months=hold,
                policy=policy,
            )
            terminal += sale.net
            res.notes.append(
                f"종료시점 매도 가정: 시세 {last.home_value:,.0f} - 양도세 "
                f"{sale.capital_gains_tax:,.0f} - 중개 {sale.brokerage:,.0f} "
                f"= 순현금 {sale.net:,.0f}"
                + ("  (1세대1주택 비과세 적용)" if sale.exempt else "")
            )

    res.terminal_net_worth = terminal
    res.npv_housing_cost = npv(cost_flows, disc)

    nm, nm_notes = nonmonetary_monthly_value(state, schedule)
    res.nonmonetary_monthly = nm
    res.nonmonetary_npv = npv([nm] * horizon, disc)
    res.adjusted_net_worth = terminal + res.nonmonetary_npv
    res.notes.extend(nm_notes)

    return res


def _decision_month(schedule: Schedule) -> int:
    for m in schedule.months:
        if m.kind != "jeonse" or m.one_off_out > 0 or m.deposit_delta != 0:
            return m.t
    return 0
