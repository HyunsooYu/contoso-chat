"""테스트용 최소 상태 생성기."""
from __future__ import annotations

import datetime as dt

from fde.models import (
    Assumptions, Asset, Budget, Candidate, Child, Debt, DepositRisk,
    Family, FamilyState, HousingCurrent, Person, Preferences,
)
from fde.policy import PolicySet, Rule


def minimal_policy(**overrides) -> PolicySet:
    """계산이 성립하는 최소 정책. 전부 0/무비용으로 두어 항등식 검증에 쓴다."""
    base = {
        "lease.renewal_cap_rate": 0.05,
        "lease.renewal_notice_window_months": [6, 2],
        "lease.min_term_months": 24,
        "lease.conversion_rate": 0.06,
        "lease.renewal_right_count": 1,
        "loan.jeonse_loan.ltv_of_deposit": 0.8,
        "loan.mortgage.default_rate": 0.04,
        "loan.mortgage.default_term_months": 360,
        "loan.mortgage.cap_amount": None,
        "loan.dsr.limit": 0.4,
        "loan.dsr.stress_add_rate": 0.0,
        "loan.dsr.include_jeonse_loan_interest": True,
        "loan.dsr.max_term_months_for_dsr": 360,
        "loan.ltv.regulated": 0.5,
        "loan.ltv.non_regulated": 0.7,
        "loan.ltv.first_home_bonus": 0.0,
        "loan.special.newborn_purchase.enabled": False,
        "loan.special.newborn_jeonse.enabled": False,
        "tax.acquisition.brackets": [{"upto": None, "rate": 0.0}],
        "tax.property.annual_rate_of_value": 0.0,
        "tax.property.comprehensive_threshold": None,
        "tax.property.comprehensive_rate": 0.0,
        "tax.capital_gains.primary_residence_exempt": True,
        "tax.capital_gains.exempt_price_cap": None,
        "tax.capital_gains.hold_months_required": 0,
        "tax.capital_gains.live_months_required": 0,
        "tax.capital_gains.rate_above_cap": 0.2,
        "tax.capital_gains.long_hold_deduction_per_year": 0.0,
        "tax.capital_gains.long_hold_deduction_max": 0.0,
        "transaction.brokerage_rate_sale": 0.0,
        "transaction.brokerage_rate_lease": 0.0,
        "transaction.legal_fee": 0.0,
        "transaction.moving_cost": 0.0,
        "transaction.interior_cost": 0.0,
        "subsidy.seoul_birth_housing.enabled": False,
        "subsidy.monthly_rent_tax_credit.enabled": False,
        "deposit_protection.hug_guarantee_fee_rate": 0.0,
        "cheongyak.special_supply_requires_no_home": False,
        "cheongyak.estimated_win_probability_per_year": 0.0,
        "cheongyak.estimated_discount_to_market": 0.0,
        "childcare.stages": [
            {"from_months": 0, "to_months": 300, "multiplier": 1.0, "label": "flat"}
        ],
        "childcare.second_child_cost_ratio": 0.0,
    }
    base.update(overrides)
    rules = {
        k: [Rule(k, v, dt.date(1900, 1, 1), confidence="verified",
                 verified_on=dt.date.today())]
        for k, v in base.items()
    }
    return PolicySet(rules, dt.date(2026, 9, 5))


def minimal_state(**overrides) -> FamilyState:
    home = Candidate(
        name="home", price_buy=500_000_000, price_jeonse=300_000_000,
        wolse_deposit=100_000_000, wolse_monthly=800_000,
        monthly_maintenance=0.0, commute_minutes={"a": 30},
    )
    st = FamilyState(
        as_of=dt.date(2026, 9, 5),
        family=Family(
            adults=[Person("a", monthly_net_income=5_000_000, annual_bonus=0.0,
                           income_growth=0.0)],
            children=[Child("kid", dt.date(2024, 12, 1))],
        ),
        assets=[Asset("cash", 200_000_000, expected_return=0.0, volatility=0.0,
                      liquidity=0)],
        debts=[],
        housing=HousingCurrent(
            kind="jeonse", deposit=300_000_000, monthly_maintenance=0.0,
            contract_start=dt.date(2025, 3, 1), contract_end=dt.date(2027, 3, 1),
            renewal_right_used=False,
            risk=DepositRisk(market_jeonse_now=300_000_000,
                             property_value=500_000_000, hug_guaranteed=True,
                             registry_checked_on=dt.date(2026, 1, 1)),
        ),
        candidates=[home],
        preferences=Preferences(max_commute_minutes=60,
                                max_housing_burden_ratio=1.0,
                                max_total_payment_ratio=1.0,
                                min_emergency_months=0,
                                answered_on=dt.date(2026, 1, 1)),
        assumptions=Assumptions(
            horizon_months=36, inflation=0.0, discount_rate=0.0,
            house_price_growth=0.0, jeonse_price_growth=0.0, wolse_growth=0.0,
            mortgage_rate=0.0, jeonse_loan_rate=0.0, deposit_rate=0.0,
            portfolio_return=0.0, portfolio_volatility=0.0,
            income_growth=0.0, living_cost_growth=0.0,
            house_price_volatility=0.0, jeonse_price_volatility=0.0,
            rate_volatility=0.0, penalty_borrow_rate=0.0,
        ),
        budget=Budget(fixed_monthly=2_000_000),
    )
    for k, v in overrides.items():
        setattr(st, k, v)
    return st
