"""세금 계산 - 전부 정책 룰셋에서 값을 읽는다. 하드코딩 없음.

10년 시뮬레이션에서 종료시점 청산가치는 **세후**여야 공정한 비교가 된다.
초안은 매도 시 양도세와 중개보수를 빼지 않아 매수 옵션을 과대평가했다.
"""
from __future__ import annotations

from dataclasses import dataclass

from fde.policy import PolicySet


def acquisition_tax(price: float, policy: PolicySet) -> float:
    """취득세(지방교육세·농특세 포함 실효세율 구간표 방식)."""
    if price <= 0:
        return 0.0
    brackets = policy.get("tax.acquisition.brackets")
    for b in brackets:
        upto = b.get("upto")
        if upto is None or price <= upto:
            return price * float(b["rate"])
    return price * float(brackets[-1]["rate"])


def property_tax_annual(value: float, policy: PolicySet) -> float:
    """재산세 + 종부세(기준 초과분)."""
    if value <= 0:
        return 0.0
    tax = value * policy.get("tax.property.annual_rate_of_value")
    threshold = policy.get("tax.property.comprehensive_threshold")
    if threshold is not None and value > threshold:
        tax += (value - threshold) * policy.get("tax.property.comprehensive_rate")
    return tax


@dataclass
class SaleResult:
    gross: float
    capital_gains_tax: float
    brokerage: float
    net: float
    taxable_gain: float
    exempt: bool


def capital_gains_tax(
    sale_price: float,
    purchase_price: float,
    acquisition_cost: float,
    hold_months: int,
    live_months: int,
    policy: PolicySet,
    is_primary_residence: bool = True,
) -> tuple[float, float, bool]:
    """(세액, 과세대상 양도차익, 비과세여부).

    1세대1주택 비과세는 고가주택 기준 초과분에만 과세되므로
    안분(按分) 방식으로 과세 양도차익을 구한다.
    """
    gain = sale_price - purchase_price - acquisition_cost
    if gain <= 0:
        return 0.0, 0.0, False

    exempt_ok = (
        is_primary_residence
        and policy.get("tax.capital_gains.primary_residence_exempt")
        and hold_months >= policy.get("tax.capital_gains.hold_months_required")
        and live_months >= policy.get("tax.capital_gains.live_months_required")
    )
    if not exempt_ok:
        rate = policy.get("tax.capital_gains.rate_above_cap")
        return gain * rate, gain, False

    cap = policy.get("tax.capital_gains.exempt_price_cap")
    if cap is None or sale_price <= cap:
        return 0.0, 0.0, True

    # 고가주택: 양도가액 중 기준초과 비율만큼만 과세
    taxable_ratio = (sale_price - cap) / sale_price
    taxable_gain = gain * taxable_ratio

    # 장기보유특별공제
    years = hold_months / 12.0
    ded = min(
        policy.get("tax.capital_gains.long_hold_deduction_max"),
        policy.get("tax.capital_gains.long_hold_deduction_per_year") * years,
    )
    taxable_gain *= 1.0 - ded

    rate = policy.get("tax.capital_gains.rate_above_cap")
    return taxable_gain * rate, taxable_gain, True


def net_sale_proceeds(
    sale_price: float,
    purchase_price: float,
    acquisition_cost: float,
    hold_months: int,
    live_months: int,
    policy: PolicySet,
    is_primary_residence: bool = True,
) -> SaleResult:
    """매도 시 실제로 손에 쥐는 현금. 시뮬레이션 종료시점 청산가치."""
    cgt, taxable, exempt = capital_gains_tax(
        sale_price, purchase_price, acquisition_cost,
        hold_months, live_months, policy, is_primary_residence,
    )
    brokerage = sale_price * policy.get("transaction.brokerage_rate_sale")
    return SaleResult(
        gross=sale_price,
        capital_gains_tax=cgt,
        brokerage=brokerage,
        net=sale_price - cgt - brokerage,
        taxable_gain=taxable,
        exempt=exempt,
    )


def monthly_rent_tax_credit(annual_rent: float, policy: PolicySet) -> float:
    """월세 세액공제 - 월 환산액. 반전세/월세 옵션의 실질 부담을 낮춘다."""
    if not policy.get("subsidy.monthly_rent_tax_credit.enabled"):
        return 0.0
    cap = policy.get("subsidy.monthly_rent_tax_credit.annual_rent_cap")
    rate = policy.get("subsidy.monthly_rent_tax_credit.credit_rate")
    return min(annual_rent, cap) * rate / 12.0
