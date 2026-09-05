"""세제·대출 게이트·보증금 리스크·예산."""
from __future__ import annotations

import datetime as dt
import unittest

from fde.budget import build_living_cost_path, evaluate_budget, required_savings_for_target
from fde.housing import assess_deposit_risk, renewal_deposit
from fde.loan import (
    dsr_max_loan, existing_annual_debt_service, ltv_max_loan,
    mortgage_capacity, newborn_purchase_loan,
)
from fde.models import Debt, DepositRisk
from fde.tax import acquisition_tax, capital_gains_tax, net_sale_proceeds, property_tax_annual
from tests.helpers import minimal_policy, minimal_state


class TestTax(unittest.TestCase):
    def setUp(self):
        self.p = minimal_policy(tax__acq=None) if False else minimal_policy(**{
            "tax.acquisition.brackets": [
                {"upto": 600_000_000, "rate": 0.011},
                {"upto": 900_000_000, "rate": 0.022},
                {"upto": None, "rate": 0.033},
            ],
            "tax.property.annual_rate_of_value": 0.0025,
            "tax.property.comprehensive_threshold": 1_200_000_000,
            "tax.property.comprehensive_rate": 0.006,
            "tax.capital_gains.exempt_price_cap": 1_200_000_000,
            "tax.capital_gains.hold_months_required": 24,
            "tax.capital_gains.live_months_required": 24,
            "tax.capital_gains.long_hold_deduction_per_year": 0.04,
            "tax.capital_gains.long_hold_deduction_max": 0.80,
            "transaction.brokerage_rate_sale": 0.005,
        })

    def test_acquisition_brackets(self):
        self.assertAlmostEqual(acquisition_tax(500_000_000, self.p), 5_500_000)
        self.assertAlmostEqual(acquisition_tax(800_000_000, self.p), 17_600_000)
        self.assertAlmostEqual(acquisition_tax(1_000_000_000, self.p), 33_000_000)
        self.assertEqual(acquisition_tax(0, self.p), 0.0)

    def test_property_tax_adds_comprehensive_above_threshold(self):
        below = property_tax_annual(1_000_000_000, self.p)
        above = property_tax_annual(1_400_000_000, self.p)
        self.assertAlmostEqual(below, 2_500_000)
        self.assertAlmostEqual(above, 3_500_000 + 200_000_000 * 0.006)

    def test_cgt_exempt_under_cap(self):
        tax, gain, exempt = capital_gains_tax(
            1_000_000_000, 700_000_000, 0, 120, 120, self.p)
        self.assertTrue(exempt)
        self.assertEqual(tax, 0.0)

    def test_cgt_taxes_only_excess_above_cap(self):
        """고가주택은 기준 초과분에만 과세된다. 전액 과세로 계산하면 매수가 과소평가된다."""
        tax, gain, exempt = capital_gains_tax(
            2_400_000_000, 1_400_000_000, 0, 120, 120, self.p)
        self.assertTrue(exempt)
        self.assertGreater(tax, 0.0)
        # 양도가 24억 중 12억 초과분 비율 = 50%, 장특공제 40%(10년)
        expected_taxable = 1_000_000_000 * 0.5 * (1 - 0.40)
        self.assertAlmostEqual(tax, expected_taxable * 0.20, delta=1.0)

    def test_cgt_not_exempt_if_hold_too_short(self):
        tax, _, exempt = capital_gains_tax(
            900_000_000, 700_000_000, 0, 12, 12, self.p)
        self.assertFalse(exempt)
        self.assertAlmostEqual(tax, 200_000_000 * 0.20)

    def test_no_gain_no_tax(self):
        tax, gain, _ = capital_gains_tax(600_000_000, 700_000_000, 0, 120, 120, self.p)
        self.assertEqual(tax, 0.0)

    def test_net_proceeds_subtract_brokerage(self):
        r = net_sale_proceeds(1_000_000_000, 700_000_000, 0, 120, 120, self.p)
        self.assertAlmostEqual(r.brokerage, 5_000_000)
        self.assertAlmostEqual(r.net, 995_000_000)


class TestLoanGates(unittest.TestCase):
    def test_bank_quote_always_wins(self):
        """자체 추정은 거의 확실히 틀린다. 은행 조회값이 있으면 그걸 쓴다."""
        s = minimal_state()
        s.bank_quotes = {"max_mortgage": 123_456_789}
        cap = mortgage_capacity(s, minimal_policy(), 800_000_000, False)
        self.assertEqual(cap.max_amount, 123_456_789)
        self.assertEqual(cap.source, "bank_quote")
        self.assertEqual(cap.caveats, [])

    def test_estimate_carries_caveats(self):
        cap = mortgage_capacity(minimal_state(), minimal_policy(), 800_000_000, False)
        self.assertEqual(cap.source, "estimated")
        self.assertTrue(any("사전조회" in c for c in cap.caveats))

    def test_ltv_binds_on_expensive_house(self):
        p = minimal_policy(**{"loan.ltv.non_regulated": 0.3})
        cap = mortgage_capacity(minimal_state(), p, 1_000_000_000, False)
        self.assertEqual(cap.binding, "ltv")
        self.assertAlmostEqual(cap.max_amount, 300_000_000)

    def test_dsr_binds_on_low_income(self):
        s = minimal_state()
        s.family.adults[0].monthly_net_income = 1_000_000
        cap = mortgage_capacity(s, minimal_policy(), 1_000_000_000, False)
        self.assertEqual(cap.binding, "dsr")

    def test_no_headroom_gives_zero(self):
        s = minimal_state()
        s.debts = [Debt("big", 2_000_000_000, 0.05, 360)]
        amt, detail = dsr_max_loan(s, minimal_policy(), 0.04)
        self.assertEqual(amt, 0.0)
        self.assertEqual(detail["annual_headroom"], 0.0)

    def test_jeonse_loan_interest_counted_when_policy_says_so(self):
        s = minimal_state()
        s.debts = [Debt("j", 100_000_000, 0.04, 24, kind="bullet", is_jeonse_loan=True)]
        on = existing_annual_debt_service(s, minimal_policy(), stressed=False)
        off = existing_annual_debt_service(
            s, minimal_policy(**{"loan.dsr.include_jeonse_loan_interest": False}),
            stressed=False)
        self.assertAlmostEqual(on, 4_000_000)
        self.assertEqual(off, 0.0)

    def test_stress_rate_reduces_capacity(self):
        s = minimal_state()
        plain, _ = dsr_max_loan(s, minimal_policy(), 0.04)
        stressed, _ = dsr_max_loan(
            s, minimal_policy(**{"loan.dsr.stress_add_rate": 0.02}), 0.04)
        self.assertLess(stressed, plain)

    def test_special_loan_gated_by_child_age(self):
        p = minimal_policy(**{
            "loan.special.newborn_purchase.enabled": True,
            "loan.special.newborn_purchase.child_age_months_max": 12,
            "loan.special.newborn_purchase.income_cap": 999_000_000_000,
            "loan.special.newborn_purchase.house_price_cap": 999_000_000_000,
            "loan.special.newborn_purchase.rate": 0.025,
            "loan.special.newborn_purchase.max_amount": 500_000_000,
        })
        s = minimal_state()          # 아이 21개월
        res = newborn_purchase_loan(s, p, 500_000_000)
        self.assertFalse(res.eligible)
        self.assertIn("개월", res.reason)


class TestDepositRisk(unittest.TestCase):
    def test_guarantee_removes_principal_risk(self):
        safe = minimal_state()
        safe.housing.risk.hug_guaranteed = True
        unsafe = minimal_state()
        unsafe.housing.risk.hug_guaranteed = False
        a = assess_deposit_risk(safe.housing, minimal_policy())
        b = assess_deposit_risk(unsafe.housing, minimal_policy())
        self.assertLess(a.prob_partial_loss, b.prob_partial_loss)
        self.assertLess(a.expected_delay_months, b.expected_delay_months)

    def test_risk_increases_with_jeonse_ratio(self):
        low = minimal_state()
        low.housing.risk = DepositRisk(
            market_jeonse_now=300_000_000, property_value=600_000_000,
            hug_guaranteed=False, registry_checked_on=dt.date(2026, 1, 1))
        high = minimal_state()
        high.housing.risk = DepositRisk(
            market_jeonse_now=560_000_000, property_value=600_000_000,
            hug_guaranteed=False, registry_checked_on=dt.date(2026, 1, 1))
        a = assess_deposit_risk(low.housing, minimal_policy())
        b = assess_deposit_risk(high.housing, minimal_policy())
        self.assertLess(a.prob_delay, b.prob_delay)

    def test_reverse_gap_detected(self):
        s = minimal_state()
        s.housing.deposit = 400_000_000
        s.housing.risk.market_jeonse_now = 350_000_000
        self.assertAlmostEqual(s.housing.reverse_gap(), 50_000_000)
        r = assess_deposit_risk(s.housing, minimal_policy())
        self.assertTrue(any("역전세" in d for d in r.drivers))

    def test_missing_registry_check_produces_top_priority_action(self):
        s = minimal_state()
        s.housing.risk.registry_checked_on = None
        r = assess_deposit_risk(s.housing, minimal_policy())
        self.assertTrue(r.actions[0].startswith("[최우선]"))

    def test_no_deposit_no_risk(self):
        s = minimal_state()
        s.housing.deposit = 0
        r = assess_deposit_risk(s.housing, minimal_policy())
        self.assertEqual(r.severity, "low")


class TestBudget(unittest.TestCase):
    def test_childcare_steps_at_elementary_entry(self):
        """초등 입학에서 육아비가 계단식으로 뛰어야 한다."""
        p = minimal_policy(**{"childcare.stages": [
            {"from_months": 0, "to_months": 84, "multiplier": 1.0, "label": "유아"},
            {"from_months": 84, "to_months": 300, "multiplier": 2.0, "label": "초등"},
        ]})
        s = minimal_state()
        s.budget.childcare_monthly = 1_000_000
        lp = build_living_cost_path(s, p, 120)
        age0 = s.family.children[0].age_months(s.as_of)     # 21
        step = 84 - age0                                     # 63
        self.assertAlmostEqual(lp.childcare[step - 1], 1_000_000, delta=1.0)
        self.assertAlmostEqual(lp.childcare[step], 2_000_000, delta=1.0)

    def test_second_child_weighted_by_probability(self):
        p = minimal_policy(**{"childcare.second_child_cost_ratio": 1.0})
        s = minimal_state()
        s.budget.childcare_monthly = 1_000_000
        s.family.second_child_probability = 0.5
        s.family.second_child_expected_date = dt.date(2027, 9, 5)
        lp = build_living_cost_path(s, p, 36)
        self.assertAlmostEqual(lp.childcare[11], 1_000_000, delta=1.0)
        self.assertAlmostEqual(lp.childcare[13], 1_500_000, delta=1.0)

    def test_burden_ratio_excludes_principal(self):
        s = minimal_state()
        v = evaluate_budget(s, 10_000_000, 4_000_000, 2_000_000, 1_000_000)
        self.assertAlmostEqual(v.housing_burden_ratio, 0.20)
        self.assertAlmostEqual(v.total_payment_ratio, 0.30)
        self.assertAlmostEqual(v.savings, 3_000_000)

    def test_deficit_is_flagged(self):
        s = minimal_state()
        v = evaluate_budget(s, 3_000_000, 4_000_000, 500_000, 0)
        self.assertTrue(any("적자" in m for m in v.messages))

    def test_required_savings(self):
        self.assertAlmostEqual(required_savings_for_target(1_200_000, 12, 0.0),
                               100_000)
        self.assertLess(required_savings_for_target(1_200_000, 12, 0.01), 100_000)


if __name__ == "__main__":
    unittest.main()
