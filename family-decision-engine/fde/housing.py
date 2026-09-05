"""전세보증금 회수 리스크.

초안 최대 결함(A-1)의 해결. 전세보증금은 자산 항목에 숫자로만 존재하는 게 아니라
**임대인에 대한 무담보 채권**이다. 만기에 안 돌아오면 이사도 매수도 전부 불가능해진다.

글라이드패스(현금 버킷)는 내 투자자산의 변동성만 통제한다. 정작 금액이 훨씬 큰
보증금이 만기에 묶이면 앞문 잠그고 뒷문 여는 것이다.

주의: 아래 확률 모델은 **투명한 휴리스틱**이지 통계적으로 추정된 모형이 아니다.
      전세가율/선순위/보증가입 여부가 위험을 단조적으로 키운다는 방향성만 담았다.
      숫자를 신뢰하지 말고, 순위와 "무엇이 위험을 키우는가"를 읽는 데 쓸 것.
      override_* 필드로 본인 판단을 직접 넣을 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.models import HousingCurrent
from fde.policy import PolicySet


@dataclass
class DepositRiskAssessment:
    prob_delay: float                 # 만기에 제때 못 받을 확률
    expected_delay_months: float      # 지연 시 예상 지연 기간
    prob_partial_loss: float          # 원금 일부 손실 확률
    expected_loss_ratio: float        # 손실 시 손실률
    severity: str                     # low | moderate | high | critical
    drivers: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        return self.severity in ("high", "critical")


def assess_deposit_risk(
    housing: HousingCurrent,
    policy: PolicySet,
    override_prob_delay: float | None = None,
    override_delay_months: float | None = None,
) -> DepositRiskAssessment:
    if housing.kind not in ("jeonse", "wolse") or housing.deposit <= 0:
        return DepositRiskAssessment(0.0, 0.0, 0.0, 0.0, "low", ["보증금 없음"])

    r = housing.risk
    drivers: list[str] = []
    actions: list[str] = []

    # --- 기본 위험도 (0~1 스케일의 투명한 가산) ---------------------
    score = 0.05

    ratio = r.jeonse_ratio
    if ratio == ratio:  # not NaN
        if ratio >= 0.90:
            score += 0.35
            drivers.append(f"전세가율 {ratio:.0%} - 깡통 구간")
        elif ratio >= 0.80:
            score += 0.20
            drivers.append(f"전세가율 {ratio:.0%} - 위험 구간")
        elif ratio >= 0.70:
            score += 0.08
            drivers.append(f"전세가율 {ratio:.0%}")
    else:
        score += 0.10
        drivers.append("주택 시세 미입력 - 전세가율 계산 불가")
        actions.append("housing.risk.property_value 를 채우세요.")

    gap = housing.reverse_gap()
    if gap > 0:
        rel = gap / housing.deposit
        score += min(0.30, 0.30 * rel / 0.15)
        drivers.append(
            f"역전세 {gap:,.0f}원 - 만기에 임대인이 자기 돈으로 메워야 하는 금액"
        )
        actions.append("임대인의 반환 능력·계획을 서면으로 확인하세요(감액 재계약 협상 포함).")

    if r.senior_debt > 0:
        rel = r.senior_debt / max(1.0, r.property_value)
        score += min(0.20, rel * 0.5)
        drivers.append(f"선순위 채권 {r.senior_debt:,.0f}원 (시세 대비 {rel:.0%})")

    if r.landlord_type in ("corporation", "multi_owner"):
        score += 0.08
        drivers.append(f"임대인 유형: {r.landlord_type}")

    if not r.confirmed_date_secured:
        score += 0.15
        drivers.append("확정일자/전입신고 미완료 - 대항력·우선변제권 없음")
        actions.insert(0, "[최우선] 전입신고 + 확정일자를 즉시 처리하세요.")

    if r.registry_checked_on is None:
        score += 0.10
        drivers.append("등기부 미확인 - 선순위 채권을 모르는 상태")
        actions.insert(0, "[최우선] 등기부등본을 열람하세요(인터넷등기소, 700원, 5분).")

    # --- 보증 가입이 사실상 전부 -----------------------------------
    if r.hug_guaranteed:
        loss_prob = 0.02
        loss_ratio = 0.05
        delay = 3.0
        drivers.append("반환보증 가입 - 원금 손실 위험은 대부분 제거됨(지연은 남음)")
    else:
        loss_prob = score * 0.5
        loss_ratio = 0.25
        delay = 6.0 + 12.0 * score
        actions.append(
            "[중대] 전세보증금반환보증(HUG/HF/SGI) 가입 가능 여부를 확인하세요. "
            "이 시스템에서 기대손실을 가장 크게 줄이는 단일 행동입니다."
        )

    prob_delay = min(0.95, score) if override_prob_delay is None else override_prob_delay
    delay_months = delay if override_delay_months is None else override_delay_months

    if r.hug_guaranteed and score < 0.35:
        severity = "low"
    elif score < 0.25:
        severity = "moderate" if not r.hug_guaranteed else "low"
    elif score < 0.45:
        severity = "high"
    else:
        severity = "critical"

    if severity in ("high", "critical"):
        actions.append(
            "만기 D-180 이전에 임차권등기명령·내용증명 절차를 미리 파악해 두세요."
        )

    return DepositRiskAssessment(
        prob_delay=prob_delay,
        expected_delay_months=delay_months,
        prob_partial_loss=min(0.9, loss_prob),
        expected_loss_ratio=loss_ratio,
        severity=severity,
        drivers=drivers,
        actions=actions,
    )


def guarantee_fee_monthly(deposit: float, policy: PolicySet) -> float:
    """반환보증 가입 시 월 보증료. 가입은 공짜가 아니므로 비용에 계상한다."""
    return deposit * policy.get("deposit_protection.hug_guarantee_fee_rate") / 12.0


def renewal_deposit(
    current_deposit: float,
    market_deposit: float,
    renewal_right_available: bool,
    policy: PolicySet,
) -> tuple[float, str]:
    """갱신 시 실제 내야 하는 보증금.

    이 함수 하나가 '현재 전세 유지' 옵션의 비용을 결정하고,
    결과적으로 매수 vs 전세 결론을 뒤집는다. (초안 결함 A-2)
    """
    if not renewal_right_available:
        return market_deposit, "갱신요구권 소진 - 시세대로 재계약"

    cap = policy.get("lease.renewal_cap_rate")
    capped = current_deposit * (1.0 + cap)
    if market_deposit <= capped:
        return market_deposit, f"시세가 상한({cap:.0%}) 이내 - 시세 적용"
    return capped, (
        f"갱신요구권 행사 - 증액 상한 {cap:.0%} 적용. "
        f"시세({market_deposit:,.0f}) 대신 {capped:,.0f} 로 계약. "
        f"절감 {market_deposit - capped:,.0f}원"
    )
