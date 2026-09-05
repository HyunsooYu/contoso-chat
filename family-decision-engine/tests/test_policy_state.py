"""정책 룰셋과 상태 로더."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fde.models import ValidationError
from fde.policy import PolicyError, load_policy
from fde.stateio import load_state, state_hash

POLICY_YAML = """
_defaults:
  effective_from: 2020-01-01
  confidence: placeholder

loan:
  ltv:
    regulated:
      value: 0.40
      effective_from: 2020-01-01
      confidence: verified
      verified_on: 2026-09-01
    non_regulated:
      value: 0.70
      confidence: placeholder
tax:
  rate:
    value: 0.05
    effective_from: 2026-01-01
    confidence: unverified
  rate_old:
    value: 0.03
    effective_from: 2020-01-01
    effective_to: 2025-12-31
    confidence: verified
    verified_on: 2026-09-01
"""


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        Path(self.dir, "p.yaml").write_text(POLICY_YAML, encoding="utf-8")

    def test_dotted_keys(self):
        p = load_policy(self.dir, dt.date(2026, 9, 5))
        self.assertEqual(p.get("loan.ltv.regulated"), 0.40)
        self.assertEqual(p.get("tax.rate"), 0.05)

    def test_effective_dating(self):
        """as-of 날짜에 따라 다른 값이 나와야 백테스트가 가능하다."""
        old = load_policy(self.dir, dt.date(2024, 6, 1))
        self.assertEqual(old.get("tax.rate_old"), 0.03)
        new = load_policy(self.dir, dt.date(2026, 6, 1))
        with self.assertRaises(PolicyError):
            new.get("tax.rate_old")          # 2025-12-31 로 만료됨

    def test_missing_key_raises_with_guidance(self):
        p = load_policy(self.dir, dt.date(2026, 9, 5))
        with self.assertRaises(PolicyError) as cm:
            p.get("does.not.exist")
        self.assertIn("config/policy", str(cm.exception))

    def test_only_used_keys_warn(self):
        """쓰지도 않은 값으로 경고를 내면 경고가 노이즈가 된다."""
        p = load_policy(self.dir, dt.date(2026, 9, 5))
        self.assertEqual(p.warnings(), [])
        p.get("loan.ltv.non_regulated")
        keys = [w.key for w in p.warnings()]
        self.assertEqual(keys, ["loan.ltv.non_regulated"])

    def test_verified_recent_does_not_warn(self):
        p = load_policy(self.dir, dt.date(2026, 9, 5))
        p.get("loan.ltv.regulated")
        self.assertEqual(p.warnings(), [])

    def test_verified_but_stale_warns(self):
        p = load_policy(self.dir, dt.date(2027, 9, 5))
        p.get("loan.ltv.regulated")
        self.assertEqual(len(p.warnings()), 1)

    def test_blocking_warnings_are_placeholders_only(self):
        p = load_policy(self.dir, dt.date(2026, 9, 5))
        p.get("loan.ltv.non_regulated")     # placeholder
        p.get("tax.rate")                   # unverified
        self.assertEqual([w.key for w in p.blocking_warnings()],
                         ["loan.ltv.non_regulated"])


STATE_YAML = """
as_of: 2026-09-05
family:
  adults:
    - name: a
      monthly_net_income: 5000000
housing:
  kind: jeonse
  deposit: 300000000
  contract_start: 2025-03-01
  contract_end: 2027-03-01
  risk:
    property_value: 500000000
    market_jeonse_now: 300000000
"""


class TestStateIo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.f = Path(self.dir, "s.yaml")
        self.f.write_text(STATE_YAML, encoding="utf-8")

    def test_load(self):
        s = load_state(self.f)
        self.assertEqual(s.housing.deposit, 300_000_000)
        self.assertEqual(s.months_to_expiry(), 5)
        self.assertEqual(s.housing.risk.jeonse_ratio, 0.6)

    def test_typo_in_key_is_an_error(self):
        """조용히 무시하면 오타 하나로 결과가 틀어진다."""
        self.f.write_text(STATE_YAML + "  depozit: 1\n", encoding="utf-8")
        with self.assertRaises(ValidationError) as cm:
            load_state(self.f)
        self.assertIn("depozit", str(cm.exception))

    def test_missing_contract_end_is_fatal(self):
        self.f.write_text(
            STATE_YAML.replace("  contract_end: 2027-03-01\n", ""), encoding="utf-8"
        )
        with self.assertRaises(ValidationError):
            load_state(self.f).validate()

    def test_hash_is_stable_and_sensitive(self):
        a = load_state(self.f)
        b = load_state(self.f)
        self.assertEqual(state_hash(a), state_hash(b))
        b.housing.deposit += 1
        self.assertNotEqual(state_hash(a), state_hash(b))

    def test_validate_flags_critical_deposit_items_first(self):
        s = load_state(self.f)
        problems = s.validate()
        self.assertTrue(any("등기부" in p for p in problems))
        self.assertTrue(any("반환보증" in p for p in problems))
        self.assertTrue(any("갱신청구권" in p for p in problems))

    def test_missing_file_message_points_to_example(self):
        with self.assertRaises(ValidationError) as cm:
            load_state(Path(self.dir, "nope.yaml"))
        self.assertIn("example", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
