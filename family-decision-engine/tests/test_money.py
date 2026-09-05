import unittest

from fde.money import (
    amortize, annuity_payment, fmt_krw, jeonse_to_wolse, monthly_rate,
    npv, remaining_balance, wolse_to_jeonse,
)


class TestAmortization(unittest.TestCase):
    def test_principal_sums_to_original(self):
        """원금 상환액의 합은 정확히 원금과 같아야 한다.

        이게 깨지면 '원금은 비용이 아니라 순자산 이전'이라는 전제가 무너진다.
        """
        for kind in ("annuity", "equal_principal", "bullet"):
            with self.subTest(kind=kind):
                sched = amortize(300_000_000, 0.045, 360, kind=kind)
                total = sum(p.principal for p in sched)
                self.assertAlmostEqual(total, 300_000_000, delta=1.0)
                self.assertAlmostEqual(sched[-1].balance_after, 0.0, delta=1.0)

    def test_annuity_payment_is_constant(self):
        sched = amortize(100_000_000, 0.05, 120, kind="annuity")
        totals = [p.total for p in sched[:-1]]
        self.assertAlmostEqual(max(totals), min(totals), delta=1.0)

    def test_annuity_formula_matches_schedule(self):
        pmt = annuity_payment(200_000_000, 0.04, 240)
        sched = amortize(200_000_000, 0.04, 240)
        self.assertAlmostEqual(pmt, sched[0].total, delta=1.0)

    def test_bullet_pays_interest_only_until_maturity(self):
        sched = amortize(100_000_000, 0.06, 24, kind="bullet")
        self.assertEqual(sum(1 for p in sched if p.principal > 0), 1)
        self.assertAlmostEqual(sched[0].interest, 100_000_000 * 0.06 / 12, delta=1.0)

    def test_io_period_defers_principal(self):
        sched = amortize(100_000_000, 0.04, 120, io_months=12)
        self.assertAlmostEqual(sum(p.principal for p in sched[:12]), 0.0, delta=1.0)
        self.assertAlmostEqual(sum(p.principal for p in sched), 100_000_000, delta=1.0)

    def test_zero_rate(self):
        sched = amortize(120_000_000, 0.0, 120)
        self.assertAlmostEqual(sched[0].principal, 1_000_000, delta=1.0)
        self.assertAlmostEqual(sum(p.interest for p in sched), 0.0, delta=1e-6)

    def test_remaining_balance_decreases(self):
        b0 = remaining_balance(300_000_000, 0.04, 360, 0)
        b1 = remaining_balance(300_000_000, 0.04, 360, 60)
        b2 = remaining_balance(300_000_000, 0.04, 360, 360)
        self.assertEqual(b0, 300_000_000)
        self.assertLess(b1, b0)
        self.assertAlmostEqual(b2, 0.0, delta=1.0)

    def test_empty_cases(self):
        self.assertEqual(amortize(0, 0.04, 120), [])
        self.assertEqual(amortize(1e8, 0.04, 0), [])
        self.assertEqual(annuity_payment(0, 0.04, 120), 0.0)


class TestConversion(unittest.TestCase):
    def test_roundtrip(self):
        """전세 <-> 월세 환산이 왕복해서 같아야 한다."""
        jeonse, deposit, conv = 400_000_000, 150_000_000, 0.06
        rent = jeonse_to_wolse(jeonse, deposit, conv)
        back = wolse_to_jeonse(deposit, rent, conv)
        self.assertAlmostEqual(back, jeonse, delta=1.0)

    def test_full_deposit_means_no_rent(self):
        self.assertEqual(jeonse_to_wolse(400_000_000, 400_000_000, 0.06), 0.0)

    def test_invalid_conversion_rate(self):
        with self.assertRaises(ValueError):
            wolse_to_jeonse(1e8, 1e6, 0.0)


class TestRatesAndNpv(unittest.TestCase):
    def test_monthly_rate_modes(self):
        self.assertAlmostEqual(monthly_rate(0.06, "nominal"), 0.005)
        self.assertAlmostEqual(monthly_rate(0.06, "effective"),
                               1.06 ** (1 / 12) - 1)
        with self.assertRaises(ValueError):
            monthly_rate(0.05, "bogus")

    def test_npv_zero_discount_is_sum(self):
        self.assertAlmostEqual(npv([100, 100, 100], 0.0), 300)

    def test_npv_discounts_later_flows(self):
        self.assertLess(npv([0, 100], 0.01), 100)
        self.assertAlmostEqual(npv([100, 0], 0.01), 100)


class TestFormatting(unittest.TestCase):
    def test_nan_and_inf_are_not_numbers(self):
        """계산 불가를 숫자처럼 보이게 하면 안 된다."""
        self.assertEqual(fmt_krw(float("nan")), "-")
        self.assertEqual(fmt_krw(float("inf")), "무한")

    def test_units(self):
        self.assertEqual(fmt_krw(50_000_000), "5,000만원")
        self.assertEqual(fmt_krw(100_000_000), "1억원")
        self.assertIn("억", fmt_krw(345_000_000))
        self.assertTrue(fmt_krw(-10_000_000).startswith("-"))


if __name__ == "__main__":
    unittest.main()
