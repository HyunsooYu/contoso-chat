"""대출 한도 - **하드 게이트**이지 점수가 아니다.

설계상 가장 중요한 결정:
  자체 DSR/LTV 계산은 거의 확실히 틀린다(은행별 가산금리·심사기준 상이,
  스트레스 DSR 적용률 단계적 변경). 틀린 한도를 믿고 계약금을 넣는 것이
  이 시스템이 낼 수 있는 최악의 결과 중 하나다.

  따라서 은행 사전조회 결과(state.bank_quotes)가 있으면 **항상 그것을 쓴다.**
  자체 계산은 "은행에 가기 전 대략의 감"과 "은행 조회값이 말이 되는지 교차검증"
  용도로만 쓰이며, 결과에 그 사실이 명시된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.models import FamilyState
from fde.money import annuity_payment, monthly_rate
from fde.policy import PolicySet


@dataclass
class LoanCapacity:
    max_amount: float
    binding: str                      # "dsr" | "ltv" | "cap" | "bank_quote"
    source: str                       # "bank_quote" | "estimated"
    detail: dict[str, float] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    @property
    def is_estimated(self) -> bool:
        return self.source == "estimated"


def existing_annual_debt_service(
    state: FamilyState, policy: PolicySet, stressed: bool = True
) -> float:
    """DSR 분자에 들어가는 기존 부채의 연간 원리금.

    전세대출은 보통 이자만 납부(만기일시)하고, 그 이자가 DSR 에 잡히는지는
    정책 룰셋이 정한다.
    """
    add = policy.get("loan.dsr.stress_add_rate") if stressed else 0.0
    include_jeonse = policy.get("loan.dsr.include_jeonse_loan_interest")

    total = 0.0
    for d in state.debts:
        if not d.counts_in_dsr:
            continue
        if d.is_jeonse_loan:
            if not include_jeonse:
                continue
            total += d.balance * (d.annual_rate + add)   # 이자만
            continue
        rate = d.annual_rate + add
        if d.kind == "bullet":
            total += d.balance * rate
        else:
            total += annuity_payment(d.balance, rate, max(1, d.term_months)) * 12
    return total


def dsr_max_loan(
    state: FamilyState,
    policy: PolicySet,
    new_loan_rate: float,
    term_months: int | None = None,
) -> tuple[float, dict[str, float]]:
    """스트레스 DSR 상한을 만족하는 최대 신규 대출 원금."""
    limit = policy.get("loan.dsr.limit")
    add = policy.get("loan.dsr.stress_add_rate")
    dsr_term = int(policy.get("loan.dsr.max_term_months_for_dsr"))
    term = min(term_months or dsr_term, dsr_term)

    income = state.family.household_annual_income()
    existing = existing_annual_debt_service(state, policy, stressed=True)
    headroom = income * limit - existing

    detail = {
        "annual_income": income,
        "dsr_limit": limit,
        "existing_annual_service": existing,
        "annual_headroom": max(0.0, headroom),
        "stress_rate": new_loan_rate + add,
        "dsr_term_months": float(term),
    }
    if headroom <= 0:
        return 0.0, detail

    # 연 상환액 headroom 을 원금으로 역산 (스트레스 금리, 원리금균등)
    stress_rate = new_loan_rate + add
    i = monthly_rate(stress_rate)
    monthly_cap = headroom / 12.0
    if abs(i) < 1e-12:
        principal = monthly_cap * term
    else:
        f = (1.0 + i) ** term
        principal = monthly_cap * (f - 1.0) / (i * f)

    detail["max_principal"] = principal
    return max(0.0, principal), detail


def ltv_max_loan(
    price: float, policy: PolicySet, is_regulated: bool, first_home: bool = False
) -> tuple[float, dict[str, float]]:
    base = policy.get(
        "loan.ltv.regulated" if is_regulated else "loan.ltv.non_regulated"
    )
    bonus = policy.get("loan.ltv.first_home_bonus") if first_home else 0.0
    ratio = min(0.9, base + bonus)
    return price * ratio, {"ltv_ratio": ratio, "price": price}


def mortgage_capacity(
    state: FamilyState,
    policy: PolicySet,
    price: float,
    is_regulated: bool,
    first_home: bool = True,
    rate: float | None = None,
    term_months: int | None = None,
) -> LoanCapacity:
    """주담대 한도. 은행 조회값이 있으면 그것을 쓴다."""
    quoted = state.bank_quotes.get("max_mortgage")
    if quoted:
        return LoanCapacity(
            max_amount=float(quoted),
            binding="bank_quote",
            source="bank_quote",
            detail={"quoted": float(quoted)},
        )

    rate = rate or state.assumptions.mortgage_rate or policy.get("loan.mortgage.default_rate")
    term = term_months or int(policy.get("loan.mortgage.default_term_months"))

    dsr_amt, dsr_detail = dsr_max_loan(state, policy, rate, term)
    ltv_amt, ltv_detail = ltv_max_loan(price, policy, is_regulated, first_home)

    candidates: list[tuple[str, float]] = [("dsr", dsr_amt), ("ltv", ltv_amt)]
    cap = policy.get("loan.mortgage.cap_amount")
    if cap:
        candidates.append(("cap", float(cap)))

    binding, amount = min(candidates, key=lambda kv: kv[1])

    caveats = [
        "자체 추정치입니다. 은행별 가산금리·심사기준이 달라 실제 한도와 차이가 납니다.",
        "매수를 진지하게 고려한다면 은행 3곳 사전조회 후 bank_quotes 에 입력하세요.",
    ]
    return LoanCapacity(
        max_amount=max(0.0, amount),
        binding=binding,
        source="estimated",
        detail={**dsr_detail, **ltv_detail},
        caveats=caveats,
    )


def jeonse_loan_capacity(
    state: FamilyState, policy: PolicySet, deposit: float
) -> LoanCapacity:
    quoted = state.bank_quotes.get("max_jeonse_loan")
    if quoted:
        return LoanCapacity(float(quoted), "bank_quote", "bank_quote", {"quoted": float(quoted)})

    ratio = policy.get("loan.jeonse_loan.ltv_of_deposit")
    return LoanCapacity(
        max_amount=deposit * ratio,
        binding="ltv",
        source="estimated",
        detail={"deposit": deposit, "ratio": ratio},
        caveats=["자체 추정치. 보증기관(HUG/HF/SGI)별 한도가 다릅니다."],
    )


# ---------------------------------------------------------------- 특례대출


@dataclass
class SpecialLoan:
    eligible: bool
    reason: str
    rate: float = 0.0
    max_amount: float = 0.0
    name: str = ""


def newborn_purchase_loan(
    state: FamilyState, policy: PolicySet, price: float
) -> SpecialLoan:
    """신생아 특례 구입자금. 자격이 되면 판을 뒤집는 유일한 정책 변수.

    서울시 주거비 지원(2년 720만원)보다 금리차 효과가 훨씬 크다.
    """
    name = "신생아 특례 구입자금(디딤돌)"
    if not policy.get("loan.special.newborn_purchase.enabled"):
        return SpecialLoan(False, "정책 룰셋에서 enabled=false. 자격 확인 후 켜세요.", name=name)

    child = state.family.youngest()
    if child is None:
        return SpecialLoan(False, "자녀 없음", name=name)

    age_cap = policy.get("loan.special.newborn_purchase.child_age_months_max")
    age = child.age_months(state.as_of)
    if age > age_cap:
        return SpecialLoan(False, f"자녀 {age}개월 > 기준 {age_cap}개월", name=name)

    income = state.family.household_annual_income()
    income_cap = policy.get("loan.special.newborn_purchase.income_cap")
    if income > income_cap:
        return SpecialLoan(False, f"소득 초과 ({income:,.0f} > {income_cap:,.0f})", name=name)

    price_cap = policy.get("loan.special.newborn_purchase.house_price_cap")
    if price > price_cap:
        return SpecialLoan(False, f"주택가액 초과 ({price:,.0f} > {price_cap:,.0f})", name=name)

    return SpecialLoan(
        True,
        "자격 충족",
        rate=policy.get("loan.special.newborn_purchase.rate"),
        max_amount=policy.get("loan.special.newborn_purchase.max_amount"),
        name=name,
    )


def newborn_jeonse_loan(state: FamilyState, policy: PolicySet) -> SpecialLoan:
    name = "신생아 특례 전세자금(버팀목)"
    if not policy.get("loan.special.newborn_jeonse.enabled"):
        return SpecialLoan(False, "정책 룰셋에서 enabled=false. 자격 확인 후 켜세요.", name=name)
    return SpecialLoan(
        True,
        "자격 충족(요건 확인 필요)",
        rate=policy.get("loan.special.newborn_jeonse.rate"),
        max_amount=policy.get("loan.special.newborn_jeonse.max_amount"),
        name=name,
    )
