"""주거 옵션 -> 월별 주거 현금흐름 스케줄.

핵심 설계 3가지:

1. **원금과 이자를 분리한다.**
   원금 상환은 비용이 아니라 순자산 이전이다. 이걸 섞으면 매수가 구조적으로
   불리해진다. consumption_out(비용) 과 principal_out(이전) 을 따로 기록한다.

2. **보증금은 자산 이동이지 비용이 아니다.**
   deposit_delta 로 따로 추적하고, 만기 회수는 지연·손실 리스크를 통과시킨다.

3. **반전세는 연속 변수다.**
   전세/반전세/월세를 이산적 3개 옵션으로 두지 않고 deposit_ratio in [0,1] 로
   둔다. 그러면 하나의 곡선 위의 점이 되고, 전세대출금리 > 전월세전환율 구간에서
   월세가 유리해지는 지점을 자동으로 찾을 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.housing import guarantee_fee_monthly, renewal_deposit
from fde.loan import jeonse_loan_capacity, mortgage_capacity, newborn_purchase_loan
from fde.models import Candidate, FamilyState
from fde.money import annuity_payment, monthly_rate
from fde.policy import PolicySet
from fde.tax import acquisition_tax, monthly_rent_tax_credit, property_tax_annual


@dataclass
class HousingMonth:
    t: int
    kind: str
    consumption_out: float = 0.0   # 이자/월세/관리비/세금/보증료 - 진짜 비용
    principal_out: float = 0.0     # 원금상환 - 순자산 이전 (비용 아님)
    one_off_out: float = 0.0       # 취득세/중개/이사/인테리어 - 비용
    lump_out: float = 0.0          # 기존 대출 일시상환 등 - 잔액이동(비용 아님, 월부담 아님)
    deposit_delta: float = 0.0     # +면 보증금 납입(현금유출), -면 반환(현금유입)
    subsidy_in: float = 0.0
    deposit_balance: float = 0.0
    home_value: float = 0.0
    debt_balance: float = 0.0
    note: str = ""

    @property
    def cash_out(self) -> float:
        return (
            self.consumption_out
            + self.principal_out
            + self.one_off_out
            + self.lump_out
            + self.deposit_delta
            - self.subsidy_in
        )


@dataclass
class Path:
    """시나리오가 제공하는 경로. 길이는 horizon+1."""

    house: list[float]        # 지수, t=0 에서 1.0
    jeonse: list[float]
    rate_delta: list[float]   # 기준 금리 대비 가산(절대값, 0.01 = +1%p)
    income: list[float]       # 소득 배수
    portfolio: list[float]    # 월 실현수익률

    @staticmethod
    def flat(n: int, monthly_portfolio_return: float = 0.0) -> "Path":
        """성장이 전혀 없는 경로. 테스트용이며 실제 비교에는 쓰지 말 것.

        포트폴리오 수익률을 0으로 두면 현금을 쥐는 옵션이 부당하게 불리해지므로
        run_decision 은 이 대신 BASE 시나리오 경로를 쓴다.
        """
        return Path([1.0] * (n + 1), [1.0] * (n + 1), [0.0] * (n + 1),
                    [1.0] * (n + 1), [monthly_portfolio_return] * (n + 1))


@dataclass
class OptionSpec:
    """비교 대상 하나."""

    name: str
    kind: str                       # jeonse | wolse | buy | wait
    candidate: Candidate
    deposit_ratio: float = 1.0      # 1.0=순수전세, 0.4=반전세, 0.2=월세 위주
    is_move: bool = True            # 이사 여부 (현재집 갱신이면 False)
    use_renewal_right: bool = False
    mortgage_term_months: int = 360
    rate_reset_months: int = 60     # 0 이면 고정금리
    label: str = ""


@dataclass
class BuildContext:
    state: FamilyState
    policy: PolicySet
    path: Path
    decision_month: int             # 전세 만기 = 옵션이 갈라지는 시점
    horizon: int
    deposit_return_month: int       # 보증금이 실제로 돌아오는 달 (지연 반영)
    deposit_recovery_ratio: float = 1.0


@dataclass
class Schedule:
    spec: OptionSpec
    months: list[HousingMonth]
    infeasible_reason: str = ""
    origination: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return not self.infeasible_reason


# ================================================================== 공통


def _pre_decision_months(ctx: BuildContext) -> list[HousingMonth]:
    """만기 전까지는 모든 옵션이 동일하다 - 현재 전세 유지.

    초안은 이걸 구분하지 않았다. 만기 전 구간이 공통이면 옵션 간 차이는
    전부 만기 이후에서만 발생하고, 비교가 훨씬 깨끗해진다.
    """
    s, p = ctx.state, ctx.policy
    h = s.housing
    out: list[HousingMonth] = []
    jl = next((d for d in s.debts if d.is_jeonse_loan), None)

    fee = guarantee_fee_monthly(h.deposit, p) if h.risk.hug_guaranteed else 0.0

    for t in range(min(ctx.decision_month, ctx.horizon)):
        interest = (jl.balance * (jl.annual_rate + ctx.path.rate_delta[t]) / 12) if jl else 0.0
        out.append(
            HousingMonth(
                t=t,
                kind="jeonse",
                consumption_out=interest + h.monthly_maintenance + fee + h.monthly_rent,
                deposit_balance=h.deposit,
                debt_balance=jl.balance if jl else 0.0,
                note="만기 전 - 전 옵션 공통",
            )
        )
    return out


def _subsidy_monthly(ctx: BuildContext, owns_home: bool) -> float:
    p = ctx.policy
    if not p.get("subsidy.seoul_birth_housing.enabled"):
        return 0.0
    if owns_home and p.get("subsidy.seoul_birth_housing.requires_no_home"):
        return 0.0
    return p.get("subsidy.seoul_birth_housing.monthly_amount")


def _market_jeonse_at(ctx: BuildContext, cand: Candidate, t: int) -> float:
    return cand.price_jeonse * ctx.path.jeonse[t]


def _market_price_at(ctx: BuildContext, cand: Candidate, t: int) -> float:
    return cand.price_buy * ctx.path.house[t]


# ================================================================== 임차


def build_lease(ctx: BuildContext, spec: OptionSpec) -> Schedule:
    """전세/반전세/월세 통합. deposit_ratio 로 연속적으로 표현한다."""
    s, p, path = ctx.state, ctx.policy, ctx.path
    h = s.housing
    T, H = ctx.decision_month, ctx.horizon
    months = _pre_decision_months(ctx)
    notes: list[str] = []

    conv = p.get("lease.conversion_rate")
    term = int(p.get("lease.min_term_months"))
    old_jl = next((d for d in s.debts if d.is_jeonse_loan), None)

    # ---- 만기 시점: 계약 조건 결정 -------------------------------
    market = _market_jeonse_at(ctx, spec.candidate, T)
    if spec.use_renewal_right and not spec.is_move:
        jeonse_equiv, why = renewal_deposit(
            h.deposit, market, not h.renewal_right_used, p
        )
        notes.append(why)
    else:
        jeonse_equiv = market

    deposit = jeonse_equiv * spec.deposit_ratio
    rent = max(0.0, (jeonse_equiv - deposit) * conv / 12.0)

    cap = jeonse_loan_capacity(s, p, deposit)
    # 전세대출은 필요한 만큼만 받는다.
    # 가용현금 = 유동자산 + (회수되는 기존 보증금) - (상환해야 할 기존 전세대출) - 이사비용
    # 기존 대출 상환을 빼지 않으면 현금이 과대계상되어 대출이 과소 산정된다.
    available = (
        s.liquid_assets()
        + h.deposit * ctx.deposit_recovery_ratio
        - (old_jl.balance if old_jl else 0.0)
        - _move_costs(ctx, spec)
    )
    loan = max(0.0, min(cap.max_amount, deposit - max(0.0, available)))

    loan_rate = s.assumptions.jeonse_loan_rate
    contract_start = T
    contract_deposit = deposit
    contract_rent = rent
    balance = loan

    fee = guarantee_fee_monthly(contract_deposit, p) if h.risk.hug_guaranteed else 0.0
    sub = _subsidy_monthly(ctx, owns_home=False)

    for t in range(T, H):
        m = HousingMonth(t=t, kind=spec.kind)

        if t == T:
            # 기존 보증금 반환은 deposit_return_month 에 발생 (지연 리스크)
            m.deposit_delta += contract_deposit
            m.one_off_out += _move_costs(ctx, spec)
            if old_jl:
                m.lump_out += old_jl.balance           # 기존 전세대출 상환(잔액이동)
            m.deposit_delta -= balance                  # 신규 대출 유입
            notes.append(
                f"신규 보증금 {contract_deposit:,.0f} / 전세대출 {balance:,.0f} / "
                f"월세 {contract_rent:,.0f}"
            )

        # 재계약 (2년마다) - 갱신권은 최초 1회만 쓸 수 있다
        if t > T and (t - contract_start) % term == 0:
            new_equiv = _market_jeonse_at(ctx, spec.candidate, t)
            new_deposit = new_equiv * spec.deposit_ratio
            delta = new_deposit - contract_deposit
            m.deposit_delta += delta                 # 증액분 현금 유출(음수면 유입)

            # 증액분의 일부를 전세대출로 조달한다면 그만큼 현금이 들어온다.
            # 이 유입을 빠뜨리면 '현금도 내고 빚도 지는' 이중 계상이 된다.
            new_cap = jeonse_loan_capacity(s, p, new_deposit).max_amount
            new_balance = max(0.0, min(new_cap, balance + max(0.0, delta)))
            m.deposit_delta -= new_balance - balance
            balance = new_balance

            contract_deposit = new_deposit
            contract_rent = max(0.0, (new_equiv - new_deposit) * conv / 12.0)
            contract_start = t
            fee = guarantee_fee_monthly(contract_deposit, p) if h.risk.hug_guaranteed else 0.0
            m.note = "재계약"

        rate = loan_rate + path.rate_delta[t]
        interest = balance * rate / 12.0
        credit = monthly_rent_tax_credit(contract_rent * 12, p)

        m.consumption_out += (
            interest + contract_rent + spec.candidate.monthly_maintenance + fee - credit
        )
        m.subsidy_in += sub
        m.deposit_balance = contract_deposit
        m.debt_balance = balance
        months.append(m)

    # 보증금 반환 (지연 반영)
    _apply_old_deposit_return(ctx, months)

    sch = Schedule(spec, months, origination={
        "deposit": contract_deposit, "loan": loan, "monthly_rent": rent,
        "jeonse_equivalent": jeonse_equiv,
    }, notes=notes)
    if cap.is_estimated:
        sch.notes.extend(cap.caveats)
    return sch


def _move_costs(ctx: BuildContext, spec: OptionSpec) -> float:
    if not spec.is_move:
        return 0.0
    p = ctx.policy
    lease_value = spec.candidate.price_jeonse
    return (
        p.get("transaction.moving_cost")
        + lease_value * p.get("transaction.brokerage_rate_lease")
    )


def _apply_old_deposit_return(ctx: BuildContext, months: list[HousingMonth]) -> None:
    """기존 전세보증금 반환. 지연되면 그 사이 유동성이 비어 페널티 차입이 발생한다.

    이게 A-1 리스크가 실제로 결과에 물리는 지점이다.
    """
    t = min(ctx.deposit_return_month, ctx.horizon - 1)
    if t < 0:
        return
    amount = ctx.state.housing.deposit * ctx.deposit_recovery_ratio
    for m in months:
        if m.t == t:
            m.deposit_delta -= amount
            if ctx.deposit_return_month > ctx.decision_month:
                m.note = (
                    (m.note + " / " if m.note else "")
                    + f"보증금 반환 {ctx.deposit_return_month - ctx.decision_month}개월 지연"
                )
            return


# ================================================================== 매수


def build_buy(ctx: BuildContext, spec: OptionSpec) -> Schedule:
    s, p, path = ctx.state, ctx.policy, ctx.path
    h = s.housing
    T, H = ctx.decision_month, ctx.horizon
    months = _pre_decision_months(ctx)
    notes: list[str] = []

    price = _market_price_at(ctx, spec.candidate, T)

    # 특례대출이 되면 판이 바뀐다
    special = newborn_purchase_loan(s, p, price)
    if special.eligible:
        rate0 = special.rate
        cap_amt = special.max_amount
        notes.append(f"{special.name} 적용: 금리 {rate0:.2%}, 한도 {cap_amt:,.0f}")
    else:
        cap = mortgage_capacity(
            s, p, price, spec.candidate.is_regulated_area,
            first_home=True, term_months=spec.mortgage_term_months,
        )
        rate0 = s.assumptions.mortgage_rate
        cap_amt = cap.max_amount
        notes.append(
            f"주담대 한도 {cap_amt:,.0f} (제약: {cap.binding}, 출처: {cap.source})"
        )
        if cap.is_estimated:
            notes.extend(cap.caveats)
        if not special.eligible:
            notes.append(f"{special.name}: 미적용 - {special.reason}")

    acq = acquisition_tax(price, p)
    one_off = (
        acq
        + price * p.get("transaction.brokerage_rate_sale")
        + p.get("transaction.legal_fee")
        + p.get("transaction.moving_cost")
        + p.get("transaction.interior_cost")
    )
    old_jl = next((d for d in s.debts if d.is_jeonse_loan), None)

    equity_available = (
        s.liquid_assets()
        + h.deposit * ctx.deposit_recovery_ratio
        - (old_jl.balance if old_jl else 0.0)
    )
    need = price + one_off
    loan = min(cap_amt, max(0.0, need - equity_available))

    if loan > cap_amt + 1:
        return Schedule(spec, months, infeasible_reason="대출 한도 초과")
    if equity_available + loan < need:
        shortfall = need - equity_available - loan
        return Schedule(
            spec, months,
            infeasible_reason=(
                f"자기자본 부족: {shortfall:,.0f}원 모자랍니다 "
                f"(필요 {need:,.0f} / 가용 {equity_available:,.0f} + 대출 {loan:,.0f})"
            ),
            notes=notes,
        )

    balance = loan
    term = spec.mortgage_term_months
    rate = rate0 + path.rate_delta[T]
    pmt = annuity_payment(balance, rate, term)
    sub = _subsidy_monthly(ctx, owns_home=True)

    for t in range(T, H):
        m = HousingMonth(t=t, kind="own")
        if t == T:
            m.deposit_delta += price          # 매수대금 (자산으로 전환)
            m.one_off_out += one_off
            m.deposit_delta -= loan           # 대출 유입
            if old_jl:
                m.lump_out += old_jl.balance      # 기존 전세대출 상환(잔액이동)

        elapsed = t - T
        # 변동금리 리셋
        if spec.rate_reset_months and elapsed > 0 and elapsed % spec.rate_reset_months == 0:
            rate = rate0 + path.rate_delta[t]
            pmt = annuity_payment(balance, rate, max(1, term - elapsed))
            m.note = f"금리 리셋 {rate:.2%}"

        i = monthly_rate(rate)
        interest = balance * i
        principal = max(0.0, min(balance, pmt - interest))
        balance = max(0.0, balance - principal)

        value = _market_price_at(ctx, spec.candidate, t)
        prop_tax = property_tax_annual(value, p) / 12.0

        m.consumption_out += interest + prop_tax + spec.candidate.monthly_maintenance
        m.principal_out += principal
        m.subsidy_in += sub
        m.home_value = value
        m.debt_balance = balance
        months.append(m)

    _apply_old_deposit_return(ctx, months)

    return Schedule(spec, months, origination={
        "price": price, "loan": loan, "acquisition_tax": acq,
        "one_off": one_off, "rate": rate0, "monthly_payment": pmt,
        "down_payment": price + one_off - loan,
    }, notes=notes)


# ================================================================== 청약 대기


def build_wait(ctx: BuildContext, spec: OptionSpec) -> Schedule:
    """무주택 유지 + 청약 대기.

    매수하는 순간 특별공급 자격(신혼부부/생애최초/다자녀)이 소멸한다.
    즉 '지금 사지 않는 것' 자체가 소멸 가능한 옵션을 보유하는 것이다.
    초안에는 청약이 Collector 에만 있고 Decision 에는 없었다.
    """
    sch = build_lease(ctx, spec)
    p = ctx.policy
    if not p.get("cheongyak.special_supply_requires_no_home"):
        sch.notes.append("청약 무주택요건 미적용 설정 - 옵션가치 0")
        return sch

    win = p.get("cheongyak.estimated_win_probability_per_year")
    disc = p.get("cheongyak.estimated_discount_to_market")
    price = spec.candidate.price_buy

    # 기대 이익을 월별로 균등 분배 (당첨 = 시세 대비 할인만큼 즉시 이익)
    monthly_ev = price * disc * win / 12.0
    for m in sch.months:
        if m.t >= ctx.decision_month:
            m.subsidy_in += monthly_ev

    sch.notes.append(
        f"청약 옵션가치: 연 당첨확률 {win:.1%} x 시세대비 할인 {disc:.0%} "
        f"= 월 기대이익 {monthly_ev:,.0f}원. "
        f"[매우 불확실] 본인 가점과 목표단지 경쟁률로 직접 추정해 교체하세요."
    )
    return sch


BUILDERS = {"jeonse": build_lease, "wolse": build_lease, "buy": build_buy, "wait": build_wait}


def build(ctx: BuildContext, spec: OptionSpec) -> Schedule:
    return BUILDERS[spec.kind](ctx, spec)
