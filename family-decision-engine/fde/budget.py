"""목표 생활비 예산 + 육아비 계단 곡선.

UC-07: 2년 뒤 순자산을 결정하는 건 (a) 저축률과 (b) 시장이다.
(b)는 통제 불가하고 예측도 안 된다. (a)는 100% 통제 가능하다.
초안은 통제 불가능한 쪽에 6개 엔진을, 통제 가능한 쪽에 대시보드 한 줄을 배정했다.

가계부 자체는 만들지 않는다(기존 앱이 훨씬 낫다). 여기서 만드는 건
범용 앱이 안 해주는 것 하나: **육아비 계단 곡선을 미리 반영한 여력 계산**.
"""
from __future__ import annotations

from dataclasses import dataclass

from fde.models import FamilyState
from fde.policy import PolicySet


@dataclass
class LivingCostPath:
    monthly: list[float]
    childcare: list[float]
    stage_labels: list[str]
    steps: list[tuple[int, str, float]]   # (month, label, new_amount)

    def at(self, t: int) -> float:
        return self.monthly[min(t, len(self.monthly) - 1)]


def _stage_multiplier(age_months: int, stages: list[dict]) -> tuple[float, str]:
    for s in stages:
        if s["from_months"] <= age_months < s["to_months"]:
            return float(s["multiplier"]), str(s["label"])
    if stages and age_months >= stages[-1]["to_months"]:
        return 0.0, "독립"
    return 1.0, "미분류"


def build_living_cost_path(
    state: FamilyState, policy: PolicySet, horizon: int
) -> LivingCostPath:
    """월별 생활비. 육아비는 계단, 나머지는 인플레이션."""
    stages = policy.get("childcare.stages")
    second_ratio = policy.get("childcare.second_child_cost_ratio")

    b = state.budget
    base_non_childcare = b.fixed_monthly + b.variable_monthly + b.other_monthly
    childcare_unit = b.childcare_monthly
    infl = state.assumptions.living_cost_growth

    monthly: list[float] = []
    childcare: list[float] = []
    labels: list[str] = []
    steps: list[tuple[int, str, float]] = []
    prev_label = None

    for t in range(horizon):
        infl_factor = (1.0 + infl) ** (t / 12.0)

        cc = 0.0
        label_parts: list[str] = []
        for child in state.family.children:
            age = child.age_months(state.as_of) + t
            mult, label = _stage_multiplier(age, stages)
            cc += childcare_unit * mult
            label_parts.append(f"{child.name}:{label}")

        # 둘째는 확률가중으로 반영 (확정이 아니므로)
        if state.family.second_child_expected_date and state.family.second_child_probability > 0:
            months_until = (
                (state.family.second_child_expected_date.year - state.as_of.year) * 12
                + (state.family.second_child_expected_date.month - state.as_of.month)
            )
            if t >= months_until:
                age2 = t - months_until
                mult2, label2 = _stage_multiplier(age2, stages)
                cc += (
                    childcare_unit * mult2 * second_ratio
                    * state.family.second_child_probability
                )
                label_parts.append(
                    f"둘째(p={state.family.second_child_probability:.0%}):{label2}"
                )

        cc *= infl_factor
        total = base_non_childcare * infl_factor + cc

        label = " / ".join(label_parts) if label_parts else "자녀 없음"
        if label != prev_label:
            steps.append((t, label, total))
            prev_label = label

        monthly.append(total)
        childcare.append(cc)
        labels.append(label)

    return LivingCostPath(monthly, childcare, labels, steps)


@dataclass
class BudgetVerdict:
    monthly_income: float
    monthly_living: float
    monthly_housing_consumption: float
    monthly_housing_total: float
    savings: float
    savings_rate: float
    housing_burden_ratio: float
    total_payment_ratio: float
    passes_burden: bool
    passes_total: bool
    messages: list[str]


def evaluate_budget(
    state: FamilyState,
    monthly_income: float,
    monthly_living: float,
    housing_consumption: float,
    housing_principal: float,
) -> BudgetVerdict:
    """주거비 부담률 상한 검사. DSR 규제 한도를 가계 목표치로 착각하면 안 된다."""
    prefs = state.preferences
    total_housing = housing_consumption + housing_principal
    savings = monthly_income - monthly_living - total_housing

    burden = housing_consumption / monthly_income if monthly_income > 0 else 9.99
    total_ratio = total_housing / monthly_income if monthly_income > 0 else 9.99

    msgs: list[str] = []
    ok_burden = burden <= prefs.max_housing_burden_ratio
    ok_total = total_ratio <= prefs.max_total_payment_ratio

    if not ok_burden:
        msgs.append(
            f"주거비 부담률 {burden:.1%} > 상한 {prefs.max_housing_burden_ratio:.0%} "
            f"(이자·월세·세금·관리비 기준, 원금 제외)"
        )
    if not ok_total:
        msgs.append(
            f"원금 포함 주거지출 {total_ratio:.1%} > 상한 {prefs.max_total_payment_ratio:.0%}"
        )
    if savings < 0:
        msgs.append(f"월 적자 {-savings:,.0f}원 - 자산을 헐어 생활하는 구조입니다.")

    return BudgetVerdict(
        monthly_income=monthly_income,
        monthly_living=monthly_living,
        monthly_housing_consumption=housing_consumption,
        monthly_housing_total=total_housing,
        savings=savings,
        savings_rate=savings / monthly_income if monthly_income > 0 else 0.0,
        housing_burden_ratio=burden,
        total_payment_ratio=total_ratio,
        passes_burden=ok_burden,
        passes_total=ok_total,
        messages=msgs,
    )


def required_savings_for_target(
    target_amount: float, months: int, monthly_return: float
) -> float:
    """목표 시점에 X원을 만들려면 월 얼마를 저축해야 하는가."""
    if months <= 0:
        return target_amount
    if abs(monthly_return) < 1e-12:
        return target_amount / months
    f = (1.0 + monthly_return) ** months
    return target_amount * monthly_return / (f - 1.0)
