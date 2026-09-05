"""가족 상태 데이터 모델.

단위 규약:
  금액 = 원(KRW), 비율 = 소수(0.05 = 5%), 기간 = 개월, 날짜 = date.

이 모델이 이 시스템의 유일한 진실 원천(single source of truth)이다.
YAML 로 손편집하고 git 으로 이력을 관리한다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal

Stability = Literal["high", "medium", "low"]
TenureKind = Literal["jeonse", "wolse", "own", "none"]


class ValidationError(Exception):
    pass


def _months_between(a: dt.date, b: dt.date) -> int:
    """a -> b 개월 수 (반내림)."""
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


# ================================================================== 가족


@dataclass
class Child:
    name: str
    birth_date: dt.date

    def age_months(self, as_of: dt.date) -> int:
        return max(0, _months_between(self.birth_date, as_of))

    def elementary_entry_date(self, cutoff_month: int = 3) -> dt.date:
        """초등학교 입학 시점(근사). 한국은 만 6세가 되는 해의 다음 3월."""
        return dt.date(self.birth_date.year + 7, cutoff_month, 1)

    def middle_school_entry_date(self, cutoff_month: int = 3) -> dt.date:
        """중학교 배정 시점(근사). 학군의 진짜 변곡점."""
        return dt.date(self.birth_date.year + 13, cutoff_month, 1)


@dataclass
class Person:
    name: str
    monthly_net_income: float = 0.0
    annual_bonus: float = 0.0
    income_growth: float = 0.02
    stability: Stability = "medium"
    work_location: str = ""
    parental_leave_months_remaining: int = 0
    leave_income_ratio: float = 0.5

    def annual_income(self) -> float:
        return self.monthly_net_income * 12 + self.annual_bonus


@dataclass
class Family:
    adults: list[Person] = field(default_factory=list)
    children: list[Child] = field(default_factory=list)
    second_child_probability: float = 0.0
    second_child_expected_date: dt.date | None = None

    def household_monthly_income(self) -> float:
        return sum(p.monthly_net_income for p in self.adults)

    def household_annual_income(self) -> float:
        return sum(p.annual_income() for p in self.adults)

    def youngest(self) -> Child | None:
        return min(self.children, key=lambda c: c.birth_date) if self.children else None

    def oldest(self) -> Child | None:
        return max(self.children, key=lambda c: c.birth_date) if self.children else None


# ================================================================== 자산/부채


@dataclass
class Asset:
    """유동성 등급과 변동성을 함께 갖는다.

    liquidity: 0=즉시현금, 1=수일, 2=수주, 3=장기(연금 등 사실상 인출불가)
    volatility: 연 표준편차. 글라이드패스가 이 값으로 현금화 우선순위를 정한다.
    """

    name: str
    amount: float
    expected_return: float = 0.0
    volatility: float = 0.0
    liquidity: int = 0
    taxable_gain_ratio: float = 0.0
    note: str = ""

    @property
    def is_liquid(self) -> bool:
        return self.liquidity <= 1

    @property
    def is_risky(self) -> bool:
        return self.volatility > 0.05


@dataclass
class Debt:
    name: str
    balance: float
    annual_rate: float
    term_months: int
    kind: str = "annuity"          # annuity | equal_principal | bullet
    io_months: int = 0
    is_jeonse_loan: bool = False
    counts_in_dsr: bool = True


# ================================================================== 보증금 리스크


@dataclass
class DepositRisk:
    """전세보증금은 무위험 자산이 아니라 임대인에 대한 무담보 채권이다.

    이 블록이 없으면 시스템 전체가 가장 큰 리스크를 못 본다.
    (초안 최대 결함 A-1)
    """

    market_jeonse_now: float = 0.0      # 현재 시세 전세가. 내 보증금보다 낮으면 역전세 노출
    property_value: float = 0.0         # 임차 주택 시세
    senior_debt: float = 0.0            # 등기부상 선순위 채권(근저당 등)
    hug_guaranteed: bool = False        # 반환보증 가입 여부 - 사실상 이게 전부
    landlord_type: str = "unknown"      # individual | corporation | multi_owner | unknown
    registry_checked_on: dt.date | None = None
    confirmed_date_secured: bool = True  # 확정일자 + 전입신고

    @property
    def jeonse_ratio(self) -> float:
        """전세가율 = (내 보증금 + 선순위채권) / 주택시세. 높을수록 위험."""
        if self.property_value <= 0:
            return float("nan")
        return (self.market_jeonse_now + self.senior_debt) / self.property_value

    @property
    def reverse_gap(self) -> float:
        """역전세 갭. 양수면 만기에 임대인이 메워야 할 금액."""
        return 0.0  # deposit 을 모르므로 HousingCurrent 에서 계산


@dataclass
class HousingCurrent:
    kind: TenureKind = "jeonse"
    deposit: float = 0.0
    monthly_rent: float = 0.0
    monthly_maintenance: float = 0.0
    contract_start: dt.date | None = None
    contract_end: dt.date | None = None
    renewal_right_used: bool = False    # 초안 최대 결함 A-2
    address: str = ""
    area_pyeong: float = 0.0
    risk: DepositRisk = field(default_factory=DepositRisk)

    def months_to_expiry(self, as_of: dt.date) -> int:
        if self.contract_end is None:
            raise ValidationError("housing.current.contract_end 가 필요합니다.")
        return _months_between(as_of, self.contract_end)

    def reverse_gap(self) -> float:
        """만기에 임대인이 새 임차인 보증금으로 못 메우는 금액."""
        if self.risk.market_jeonse_now <= 0:
            return 0.0
        return max(0.0, self.deposit - self.risk.market_jeonse_now)


# ================================================================== 후보지


@dataclass
class Candidate:
    """비교 대상 주거 후보. 매수/전세/월세 각각의 시세를 함께 갖는다."""

    name: str
    area: str = ""
    price_buy: float = 0.0
    price_jeonse: float = 0.0
    wolse_deposit: float = 0.0
    wolse_monthly: float = 0.0
    monthly_maintenance: float = 300_000.0
    commute_minutes: dict[str, int] = field(default_factory=dict)  # person -> 편도 분
    daycare_minutes: int = 0
    school_score: float = 0.5           # 0~1, 화폐화 불가 항목
    satisfaction_score: float = 0.5     # 0~1
    grandparents_minutes: int = 0
    is_regulated_area: bool = False
    note: str = ""

    def total_daily_commute_minutes(self) -> int:
        """세대 전체 왕복 통근 분. 시간의 화폐가치 환산에 쓰인다."""
        return sum(m * 2 for m in self.commute_minutes.values())


# ================================================================== 선호(swing weighting)


@dataclass
class Preferences:
    """가중치를 임의로 정하지 않고, 답할 수 있는 trade-off 질문으로 받는다.

    "육아 25% / 주거비 25%" 같은 가중치는 근거를 댈 수 없지만
    "통근 20분 단축에 월 25만원 낼 의향이 있나"는 답할 수 있다.
    (초안 결함 A-3 / UC-08 부부 합의 도구)
    """

    krw_per_commute_minute_month: float = 0.0
    """편도 1분 단축의 월 지불의사액. 예) 20분 단축에 월 25만원 -> 12500"""

    krw_per_daycare_minute_month: float = 0.0
    krw_per_grandparent_minute_month: float = 0.0

    school_quality_wtp_monthly: float = 0.0
    """school_score 1.0 vs 0.0 의 월 지불의사 차이."""

    satisfaction_wtp_monthly: float = 0.0

    max_commute_minutes: int = 60
    """이 값을 넘으면 하드 탈락. 점수화하지 않는다."""

    max_housing_burden_ratio: float = 0.30
    """(이자+월세+세금+관리비) / 가처분소득 상한. 원금상환 제외."""

    max_total_payment_ratio: float = 0.40
    """원금 포함 총 주거 지출 / 가처분소득 상한."""

    min_emergency_months: int = 6
    max_forced_move_probability: float = 0.05
    max_liquidity_breach_probability: float = 0.05

    answered_on: dt.date | None = None
    answered_by: str = ""


# ================================================================== 가정


@dataclass
class Assumptions:
    horizon_months: int = 120
    inflation: float = 0.022
    discount_rate: float = 0.03          # 실질 할인율(연)

    house_price_growth: float = 0.02
    jeonse_price_growth: float = 0.03
    wolse_growth: float = 0.02
    mortgage_rate: float = 0.042
    jeonse_loan_rate: float = 0.038
    deposit_rate: float = 0.030          # 예금/MMF
    portfolio_return: float = 0.05
    portfolio_volatility: float = 0.12

    income_growth: float = 0.03
    living_cost_growth: float = 0.025

    house_price_volatility: float = 0.09
    jeonse_price_volatility: float = 0.07
    rate_volatility: float = 0.010

    penalty_borrow_rate: float = 0.09    # 유동성 부족 시 신용대출 금리

    # 상관계수 - 리뷰 A-5. 금리↑ + 자산가격↓ + 소득충격은 같이 온다.
    corr_house_jeonse: float = 0.55
    corr_house_rate: float = -0.35
    corr_jeonse_rate: float = -0.15
    corr_house_income: float = 0.25


@dataclass
class Budget:
    """목표 생활비. UC-07 - 유일한 고빈도 유스케이스."""

    fixed_monthly: float = 0.0           # 보험/통신/구독 등
    variable_monthly: float = 0.0        # 식비/생활
    childcare_monthly: float = 0.0       # 현재 육아비 (곡선은 budget.py 가 생성)
    other_monthly: float = 0.0
    target_savings_rate: float | None = None

    def base_living_cost(self) -> float:
        return (
            self.fixed_monthly
            + self.variable_monthly
            + self.childcare_monthly
            + self.other_monthly
        )


# ================================================================== 최상위


@dataclass
class FamilyState:
    as_of: dt.date
    family: Family
    assets: list[Asset] = field(default_factory=list)
    debts: list[Debt] = field(default_factory=list)
    housing: HousingCurrent = field(default_factory=HousingCurrent)
    candidates: list[Candidate] = field(default_factory=list)
    preferences: Preferences = field(default_factory=Preferences)
    assumptions: Assumptions = field(default_factory=Assumptions)
    budget: Budget = field(default_factory=Budget)
    bank_quotes: dict[str, float] = field(default_factory=dict)
    """은행 사전조회 결과. 있으면 자체 DSR/LTV 계산보다 **항상 우선**한다.
    (UC-04: 자체 한도 계산은 부정적 가치)
    키: max_mortgage, max_jeonse_loan, quoted_mortgage_rate, quoted_on"""

    # ---- 파생 -------------------------------------------------------

    def liquid_assets(self) -> float:
        return sum(a.amount for a in self.assets if a.is_liquid)

    def total_assets(self) -> float:
        return sum(a.amount for a in self.assets) + self.housing.deposit

    def total_debt(self) -> float:
        return sum(d.balance for d in self.debts)

    def net_worth(self) -> float:
        return self.total_assets() - self.total_debt()

    def risky_assets(self) -> float:
        return sum(a.amount for a in self.assets if a.is_risky)

    def months_to_expiry(self) -> int:
        return self.housing.months_to_expiry(self.as_of)

    def monthly_debt_service(self) -> float:
        from fde.money import annuity_payment

        total = 0.0
        for d in self.debts:
            if d.kind == "bullet":
                total += d.balance * d.annual_rate / 12
            else:
                total += annuity_payment(d.balance, d.annual_rate, max(1, d.term_months))
        return total

    # ---- 검증 -------------------------------------------------------

    def validate(self) -> list[str]:
        """치명적이지 않은 문제는 경고로 반환. 치명적이면 raise."""
        problems: list[str] = []

        if self.housing.contract_end is None:
            raise ValidationError(
                "housing.contract_end 는 필수입니다. 이 시스템의 시간축 원점입니다."
            )
        if not self.family.adults:
            raise ValidationError("family.adults 가 비어 있습니다.")

        if self.months_to_expiry() < 0:
            problems.append(
                f"전세 만기({self.housing.contract_end})가 as_of({self.as_of})보다 과거입니다."
            )

        h = self.housing
        if h.kind == "jeonse":
            if h.risk.registry_checked_on is None:
                problems.append(
                    "[중대] 등기부 확인일이 없습니다. 보증금 회수 리스크를 평가할 수 없습니다. "
                    "이게 이 시스템에서 기대손실이 가장 큰 항목입니다(수억 원 규모)."
                )
            if not h.risk.hug_guaranteed:
                problems.append(
                    "[중대] 전세보증금반환보증 미가입입니다. 가입 가능 여부부터 확인하세요."
                )
            if h.risk.property_value <= 0:
                problems.append("housing.risk.property_value 가 없어 전세가율을 못 냅니다.")
            elif h.risk.jeonse_ratio > 0.8:
                problems.append(
                    f"전세가율 {h.risk.jeonse_ratio:.0%} - 선순위 포함 80% 초과. 위험구간입니다."
                )
            if h.reverse_gap() > 0:
                problems.append(
                    f"역전세 노출: 현재 시세 전세가가 내 보증금보다 "
                    f"{h.reverse_gap():,.0f}원 낮습니다."
                )
            if not h.renewal_right_used:
                problems.append(
                    "[기회] 계약갱신청구권 미사용 상태입니다. "
                    "갱신 시 증액 상한이 적용되므로 '현재 전세 유지'가 크게 유리할 수 있습니다."
                )

        if self.preferences.answered_on is None:
            problems.append(
                "preferences 가 미작성입니다. 통근/육아 가치가 0으로 계산되어 "
                "가까운 집의 이점이 완전히 무시됩니다. `python -m fde tradeoffs` 를 먼저 하세요."
            )

        if not self.bank_quotes.get("max_mortgage"):
            problems.append(
                "은행 대출한도 사전조회 결과가 없습니다. 자체 DSR 추정치를 쓰게 되며 "
                "이는 실제와 다를 수 있습니다(은행별 상이). 매수를 진지하게 고려한다면 "
                "은행 3곳 사전조회 후 bank_quotes 에 입력하세요."
            )

        if not self.candidates:
            problems.append("candidates 가 비어 있어 이사/매수 옵션을 비교할 수 없습니다.")

        return problems
