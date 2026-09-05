"""금융 계산 커널.

모든 금액의 단위는 **원(KRW)** 이고 float 로 다룬다. 표시할 때만 만원/억으로 반올림한다.
모든 함수는 순수 함수다 - 상태를 읽거나 쓰지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

MAN = 10_000.0
EOK = 100_000_000.0


# ---------------------------------------------------------------- 이자율 변환


def monthly_rate(annual_rate: float, compounding: str = "nominal") -> float:
    """연율 -> 월율.

    compounding="nominal": 은행 대출/예금 표기 관행 (연 6% -> 월 0.5%).
    compounding="effective": 실효 복리 (연 6% -> (1.06)^(1/12)-1).

    대출 상환 스케줄은 국내 관행상 nominal 을 쓰고,
    투자수익률 같은 실효 수익률은 effective 를 쓴다.
    """
    if compounding == "nominal":
        return annual_rate / 12.0
    if compounding == "effective":
        return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0
    raise ValueError(f"unknown compounding: {compounding!r}")


def real_rate(nominal: float, inflation: float) -> float:
    """피셔 방정식. 명목 -> 실질."""
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


# ---------------------------------------------------------------- 현재가치


def npv(cashflows: list[float], monthly_discount: float) -> float:
    """cashflows[i] 는 i개월 말 발생. i=0 은 할인하지 않는다."""
    total = 0.0
    for i, cf in enumerate(cashflows):
        total += cf / ((1.0 + monthly_discount) ** i)
    return total


def pv(amount: float, months: int, monthly_discount: float) -> float:
    return amount / ((1.0 + monthly_discount) ** months)


# ---------------------------------------------------------------- 대출 상환


@dataclass(frozen=True)
class Payment:
    """한 달치 상환 내역. interest 는 비용, principal 은 순자산 이전(비용 아님)."""

    interest: float
    principal: float
    balance_after: float

    @property
    def total(self) -> float:
        return self.interest + self.principal


def annuity_payment(principal: float, annual_rate: float, months: int) -> float:
    """원리금균등 월 상환액."""
    if months <= 0:
        return 0.0
    if principal <= 0:
        return 0.0
    i = monthly_rate(annual_rate)
    if abs(i) < 1e-12:
        return principal / months
    factor = (1.0 + i) ** months
    return principal * i * factor / (factor - 1.0)


def amortize(
    principal: float,
    annual_rate: float,
    term_months: int,
    kind: str = "annuity",
    io_months: int = 0,
) -> list[Payment]:
    """상환 스케줄 생성.

    kind:
      "annuity"       원리금균등
      "equal_principal" 원금균등
      "bullet"        만기일시 (이자만 납부, 만기에 원금)

    io_months: 거치기간(이자만). annuity/equal_principal 에만 적용.
    """
    if principal <= 0 or term_months <= 0:
        return []

    i = monthly_rate(annual_rate)
    sched: list[Payment] = []

    if kind == "bullet":
        for m in range(term_months):
            interest = principal * i
            prin = principal if m == term_months - 1 else 0.0
            bal = 0.0 if m == term_months - 1 else principal
            sched.append(Payment(interest, prin, bal))
        return sched

    io_months = min(io_months, term_months)
    balance = principal
    for _ in range(io_months):
        sched.append(Payment(balance * i, 0.0, balance))

    repay_months = term_months - io_months
    if repay_months <= 0:
        return sched

    if kind == "annuity":
        pmt = annuity_payment(balance, annual_rate, repay_months)
        for m in range(repay_months):
            interest = balance * i
            prin = pmt - interest
            if m == repay_months - 1:  # 잔여 반올림 흡수
                prin = balance
            balance = max(0.0, balance - prin)
            sched.append(Payment(interest, prin, balance))
    elif kind == "equal_principal":
        prin_fixed = balance / repay_months
        for m in range(repay_months):
            interest = balance * i
            prin = balance if m == repay_months - 1 else prin_fixed
            balance = max(0.0, balance - prin)
            sched.append(Payment(interest, prin, balance))
    else:
        raise ValueError(f"unknown amortization kind: {kind!r}")

    return sched


def remaining_balance(
    principal: float, annual_rate: float, term_months: int, elapsed: int, **kw
) -> float:
    sched = amortize(principal, annual_rate, term_months, **kw)
    if not sched:
        return 0.0
    if elapsed <= 0:
        return principal
    return sched[min(elapsed, len(sched)) - 1].balance_after


# ---------------------------------------------------------------- 전월세 전환


def jeonse_to_wolse(
    jeonse_deposit: float, target_deposit: float, conversion_rate: float
) -> float:
    """전세보증금 일부를 월세로 전환했을 때의 월세액.

    conversion_rate 는 연율(전월세전환율). 국내 관행상
      월세 = (전세보증금 - 보증금) * 전환율 / 12
    """
    gap = max(0.0, jeonse_deposit - target_deposit)
    return gap * conversion_rate / 12.0


def wolse_to_jeonse(
    deposit: float, monthly_rent: float, conversion_rate: float
) -> float:
    """월세 계약의 전세 환산가."""
    if conversion_rate <= 0:
        raise ValueError("conversion_rate must be > 0")
    return deposit + monthly_rent * 12.0 / conversion_rate


# ---------------------------------------------------------------- 성장/인플레


def grow(amount: float, annual_rate: float, months: int) -> float:
    return amount * (1.0 + annual_rate) ** (months / 12.0)


def monthly_growth_factor(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 12.0)


# ---------------------------------------------------------------- 표시


def fmt_krw(amount: float, unit: str = "auto") -> str:
    """사람이 읽는 금액. 기본은 억/만원 혼용."""
    if amount != amount:            # NaN - 계산 불가를 숫자처럼 보이게 하지 않는다
        return "-"
    if amount in (float("inf"), float("-inf")):
        return "무한"
    sign = "-" if amount < 0 else ""
    a = abs(amount)
    if unit == "man" or (unit == "auto" and a < EOK):
        return f"{sign}{a / MAN:,.0f}만원"
    eok = int(a // EOK)
    rest_man = (a - eok * EOK) / MAN
    if rest_man < 0.5:
        return f"{sign}{eok}억원"
    return f"{sign}{eok}억 {rest_man:,.0f}만원"


def fmt_pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}%"
