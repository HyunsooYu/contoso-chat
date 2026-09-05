"""현금 버킷 + 만기 연동 글라이드패스.

초안 6번을 유지하되 A-1을 반영해 확장했다.

초안의 글라이드패스는 **내 투자자산의 변동성만** 통제한다. 정작 금액이 훨씬 큰
보증금이 만기에 안 돌아오면 앞문 잠그고 뒷문 여는 것이다. 그래서 보증보험
미가입이면 '브릿지 예비비'를 별도 버킷으로 강제한다.

목적: 주식이나 BTC가 -30%일 때 전세 계약이 만료되는 사고를 막는 것.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.budget import LivingCostPath
from fde.housing import assess_deposit_risk, renewal_deposit
from fde.models import FamilyState
from fde.money import fmt_krw
from fde.policy import PolicySet


@dataclass
class Bucket:
    key: str
    label: str
    target: float
    rationale: str
    deadline_months: int | None = None
    max_volatility: float = 0.0
    priority: int = 0          # 낮을수록 먼저 채운다

    def render(self) -> str:
        d = f" (D-{self.deadline_months * 30}일 내)" if self.deadline_months else ""
        return f"{self.label}: {fmt_krw(self.target)}{d} - {self.rationale}"


@dataclass
class GlidePhase:
    name: str
    months_to_expiry_from: int
    months_to_expiry_to: int
    max_risky_ratio_of_housing_fund: float
    instruction: str


GLIDE = [
    GlidePhase("정상", 24, 10**6, 1.00,
               "주거자금도 위험자산에 둘 수 있음. 만기가 충분히 멀다."),
    GlidePhase("확보 시작", 12, 24, 0.50,
               "주거자금의 절반을 안전자산으로 이전 시작."),
    GlidePhase("변동성 최소화", 6, 12, 0.20,
               "주거자금 대부분을 예금/파킹으로. 여기서부터는 수익률이 아니라 확실성."),
    GlidePhase("전액 현금화", 0, 6, 0.00,
               "필요 보증금·계약금 전액을 즉시 인출 가능한 현금으로. 예외 없음."),
]


def current_phase(months_to_expiry: int) -> GlidePhase:
    for ph in GLIDE:
        if ph.months_to_expiry_from <= months_to_expiry < ph.months_to_expiry_to:
            return ph
    return GLIDE[-1]


@dataclass
class Allocation:
    buckets: list[Bucket]
    phase: GlidePhase
    months_to_expiry: int
    total_liquid: float
    total_risky: float
    required_safe: float
    risky_over_limit: float
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_target(self) -> float:
        return sum(b.target for b in self.buckets)

    @property
    def investable(self) -> float:
        return max(0.0, self.total_liquid - self.total_target)


def build_buckets(
    state: FamilyState,
    policy: PolicySet,
    living: LivingCostPath,
    housing_need: float | None = None,
) -> Allocation:
    """5개 버킷의 목표액과, 지금 무엇을 팔아야 하는지."""
    m = state.months_to_expiry()
    phase = current_phase(m)
    prefs = state.preferences
    risk = assess_deposit_risk(state.housing, policy)

    buckets: list[Bucket] = []
    warnings: list[str] = []

    # ① 생활 안전자금
    emergency = living.at(0) * prefs.min_emergency_months
    buckets.append(Bucket(
        "emergency", "① 생활안전자금", emergency,
        f"월 생활비 {fmt_krw(living.at(0))} x {prefs.min_emergency_months}개월",
        max_volatility=0.0, priority=0,
    ))

    # ② 주거자금 - 만기에 실제로 필요한 현금
    if housing_need is None:
        market = state.housing.risk.market_jeonse_now or state.housing.deposit
        new_deposit, _ = renewal_deposit(
            state.housing.deposit, market,
            not state.housing.renewal_right_used, policy,
        )
        increase = max(0.0, new_deposit - state.housing.deposit)
        move_cost = (
            policy.get("transaction.moving_cost")
            + market * policy.get("transaction.brokerage_rate_lease")
        )
        housing_need = increase + move_cost
    buckets.append(Bucket(
        "housing", "② 주거자금", housing_need,
        "보증금 증액분 + 이사·중개비 (매수 검토 시 계약금으로 대체)",
        deadline_months=max(0, m), max_volatility=0.0, priority=1,
    ))

    # ②-B 브릿지 예비비 - A-1 리스크의 실제 대비책
    if not state.housing.risk.hug_guaranteed and risk.prob_delay > 0.05:
        bridge = living.at(0) * 6 + housing_need
        buckets.append(Bucket(
            "bridge", "②-B 보증금 지연 브릿지", bridge,
            (f"반환보증 미가입 상태. 만기에 보증금이 지연될 확률 "
             f"{risk.prob_delay:.0%}, 예상 지연 {risk.expected_delay_months:.0f}개월. "
             f"그 기간을 버틸 현금."),
            deadline_months=max(0, m), max_volatility=0.0, priority=1,
        ))
        warnings.append(
            "보증보험에 가입하면 이 버킷(브릿지 예비비)이 거의 통째로 사라집니다. "
            "즉 보증료가 이 금액을 묶어두는 기회비용보다 싸다면 가입이 명백히 이득입니다."
        )

    # ③ 단기 가족자금
    family_reserve = living.at(0) * 3
    buckets.append(Bucket(
        "family", "③ 단기 가족자금", family_reserve,
        "육아/교육/의료/차량 등 1년 내 예상 지출", max_volatility=0.05, priority=2,
    ))

    # ④ 기회자금
    opportunity = state.liquid_assets() * 0.10
    buckets.append(Bucket(
        "opportunity", "④ 기회자금", opportunity,
        "시장 급락 시 추가매수 / 급매 대응", max_volatility=0.10, priority=3,
    ))

    total_liquid = state.liquid_assets()
    risky = state.risky_assets()

    # 글라이드패스 검사
    safe_needed = sum(
        b.target for b in buckets if b.key in ("emergency", "housing", "bridge")
    )
    allowed_risky_in_housing = safe_needed * phase.max_risky_ratio_of_housing_fund
    safe_available = total_liquid - risky
    shortfall = max(0.0, safe_needed - allowed_risky_in_housing - safe_available)

    actions: list[str] = []
    if shortfall > 0:
        actions.append(
            f"[{phase.name}] 안전자산이 {fmt_krw(shortfall)} 부족합니다. "
            f"변동성이 큰 자산부터 현금화하세요:"
        )
        remaining = shortfall
        for a in sorted(
            [x for x in state.assets if x.is_risky and x.is_liquid],
            key=lambda x: -x.volatility,
        ):
            if remaining <= 0:
                break
            sell = min(a.amount, remaining)
            actions.append(
                f"   - {a.name} {fmt_krw(sell)} 매도 "
                f"(변동성 {a.volatility:.0%}, 보유 {fmt_krw(a.amount)})"
            )
            remaining -= sell
        if remaining > 0:
            actions.append(
                f"   - 위험자산을 다 팔아도 {fmt_krw(remaining)} 부족합니다. "
                f"주거 옵션(보증금 규모)을 낮추거나 대출로 메워야 합니다."
            )
    else:
        actions.append(f"[{phase.name}] 글라이드패스 요건 충족. 추가 현금화 불필요.")

    if total_liquid < safe_needed:
        warnings.append(
            f"유동자산({fmt_krw(total_liquid)})이 만기에 필요한 현금"
            f"({fmt_krw(safe_needed)})보다 적습니다."
        )

    return Allocation(
        buckets=buckets, phase=phase, months_to_expiry=m,
        total_liquid=total_liquid, total_risky=risky,
        required_safe=safe_needed, risky_over_limit=shortfall,
        actions=actions, warnings=warnings,
    )
