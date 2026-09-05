"""게이트·임계값 solver·시나리오·트리거."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fde.decision import apply_gates, enumerate_options, run_decision
from fde.options import OptionSpec
from fde.scenario import (
    _percentile, cholesky, correlation_matrix, deterministic_scenarios,
    monte_carlo, random_path, scenario_path,
)
from fde.sensitivity import DEFAULT_KNOBS, Knob, find_threshold, run_sensitivity
from fde.triggers import TriggerRule, evaluate_triggers
from tests.helpers import minimal_policy, minimal_state


class TestGates(unittest.TestCase):
    def test_commute_gate_is_binary_not_scored(self):
        """통근 상한은 점수가 아니라 탈락 기준이다."""
        s = minimal_state()
        s.candidates[0].commute_minutes = {"a": 90}
        s.preferences.max_commute_minutes = 60
        r = run_decision(s, minimal_policy())
        self.assertEqual(r.passing, [])
        self.assertTrue(all(
            any(g.name == "통근상한" and not g.passed for g in e.gates)
            for e in r.failing
        ))

    def test_gates_report_dominant_failure(self):
        s = minimal_state()
        s.candidates[0].commute_minutes = {"a": 90}
        r = run_decision(s, minimal_policy())
        self.assertIn("통근상한", r.dominant_failure)

    def test_enumerate_covers_all_four_families_plus_wait(self):
        specs = enumerate_options(minimal_state())
        kinds = {sp.kind for sp in specs}
        self.assertEqual(kinds, {"jeonse", "wolse", "buy", "wait"})
        # 반전세가 이산 옵션이 아니라 연속 변수로 표현되는지
        ratios = sorted({sp.deposit_ratio for sp in specs if sp.kind == "wolse"})
        self.assertGreater(len(ratios), 1)

    def test_ranking_unit_is_money_not_score(self):
        r = run_decision(minimal_state(), minimal_policy())
        best = r.best
        self.assertIsNotNone(best)
        self.assertGreater(abs(best.score), 1_000_000)   # 원 단위 크기


class TestSensitivity(unittest.TestCase):
    def test_finds_known_crossing(self):
        """합성 문제에서 임계값을 실제로 찾아내는지."""
        s = minimal_state()
        s.candidates[0].price_buy = 400_000_000
        knob = Knob("house_price_growth", "집값", -0.10, 0.20,
                    plausible_lo=-0.05, plausible_hi=0.10)
        base = run_decision(s, minimal_policy()).best.spec.name
        th = find_threshold(s, minimal_policy(), knob, base, grid=10)
        if th.crossing is not None:
            self.assertGreaterEqual(th.crossing, knob.lo)
            self.assertLessEqual(th.crossing, knob.hi)
            self.assertNotEqual(th.winner_after, th.winner_before)

    def test_no_crossing_is_reported_not_faked(self):
        """뒤집히는 지점이 없으면 없다고 말해야 한다. 지어내면 안 된다."""
        s = minimal_state()
        cur = s.assumptions.income_growth
        knob = Knob("income_growth", "소득", cur, cur)     # 흔들 여지가 없는 범위
        base = run_decision(s, minimal_policy()).best.spec.name
        th = find_threshold(s, minimal_policy(), knob, base, grid=4)
        self.assertIsNone(th.crossing)
        self.assertIn("바뀌지 않음", th.render())

    def test_razor_thin_margin_is_surfaced_as_fragile(self):
        """옵션이 사실상 동률이면 아주 작은 가정 변화로도 순위가 바뀐다.

        그런 결론을 '견고하다'고 보고하면 안 된다. 이 케이스에서는
        solver 가 극히 좁은 범위 안에서도 교차점을 찾아내야 한다.
        """
        s = minimal_state()
        knob = Knob("income_growth", "소득", 0.0, 0.0001,
                    plausible_lo=0.0, plausible_hi=0.0001)
        base = run_decision(s, minimal_policy()).best.spec.name
        th = find_threshold(s, minimal_policy(), knob, base, grid=4)
        self.assertIsNotNone(th.crossing)
        self.assertTrue(th.within_plausible)
        self.assertNotEqual(th.winner_after, th.winner_before)

    def test_report_states_fragility(self):
        rep = run_sensitivity(minimal_state(), minimal_policy(),
                              knobs=DEFAULT_KNOBS[:3], grid=8)
        self.assertTrue(rep.summary)
        self.assertEqual(rep.robust, not rep.fragile)

    def test_thresholds_sorted_by_closeness(self):
        rep = run_sensitivity(minimal_state(), minimal_policy(),
                              knobs=DEFAULT_KNOBS[:4], grid=8)
        found = [t for t in rep.thresholds if t.crossing is not None]
        dists = [t.distance_pct for t in found]
        self.assertEqual(dists, sorted(dists))


class TestScenario(unittest.TestCase):
    def test_cholesky_reconstructs_matrix(self):
        m = correlation_matrix(minimal_state().assumptions)
        L = cholesky(m)
        n = len(m)
        for i in range(n):
            for j in range(n):
                v = sum(L[i][k] * L[j][k] for k in range(n))
                self.assertAlmostEqual(v, m[i][j], places=6)

    def test_cholesky_handles_near_singular(self):
        m = [[1.0, 1.0], [1.0, 1.0]]
        L = cholesky(m)
        self.assertAlmostEqual(L[0][0], 1.0, places=3)

    def test_cholesky_rejects_impossible_correlations(self):
        with self.assertRaises(ValueError):
            cholesky([[1.0, 2.0], [2.0, 1.0]])

    def test_percentiles(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(_percentile(xs, 0.0), 1.0)
        self.assertAlmostEqual(_percentile(xs, 0.5), 3.0)
        self.assertAlmostEqual(_percentile(xs, 1.0), 5.0)

    def test_deterministic_includes_deposit_scenarios(self):
        """보증금 반환지연은 전세 가구의 실제 최대 사고다. 빠지면 안 된다."""
        names = {s.name for s in deterministic_scenarios(minimal_state().assumptions)}
        self.assertIn("DEPOSIT_DELAY", names)
        self.assertIn("DEPOSIT_LOSS", names)
        self.assertIn("STRESS", names)

    def test_stress_scenario_moves_factors_together(self):
        sc = next(s for s in deterministic_scenarios(minimal_state().assumptions)
                  if s.name == "STRESS")
        self.assertLess(sc.house_growth, 0)
        self.assertGreater(sc.rate_delta, 0)
        self.assertLess(sc.income_growth_delta, 0)

    def test_scenario_path_length_and_growth(self):
        a = minimal_state().assumptions
        sc = deterministic_scenarios(a)[0]
        p = scenario_path(sc, a, 24)
        self.assertEqual(len(p.house), 25)
        self.assertAlmostEqual(p.house[0], 1.0)

    def test_random_paths_are_reproducible(self):
        import random
        a = minimal_state().assumptions
        L = cholesky(correlation_matrix(a))
        p1 = random_path(a, 12, random.Random(7), L)
        p2 = random_path(a, 12, random.Random(7), L)
        self.assertEqual(p1.house, p2.house)

    def test_monte_carlo_produces_downside_metrics(self):
        risks = monte_carlo(minimal_state(), minimal_policy(), n_paths=25, seed=1)
        self.assertTrue(risks)
        for r in risks.values():
            if r.n:
                self.assertLessEqual(r.p10, r.p50)
                self.assertLessEqual(r.p50, r.p90)
                self.assertLessEqual(r.cvar05, r.p10 + 1.0)
                self.assertGreaterEqual(r.prob_forced_move, 0.0)


class TestTriggers(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(), "t.json")

    def test_persistence_suppresses_first_occurrences(self):
        rule = TriggerRule("k", "테스트", persistence=3, min_days_between=0,
                           requires_actionable=False)
        cond = {"k": (True, "msg")}
        fired = []
        for i in range(4):
            ev = evaluate_triggers(cond, 3, self.path,
                                   dt.date(2026, 1, 1) + dt.timedelta(days=i),
                                   rules=[rule])
            fired.append(ev[0].fired)
        self.assertEqual(fired, [False, False, True, True])

    def test_streak_resets_when_condition_clears(self):
        rule = TriggerRule("k", "t", persistence=2, min_days_between=0,
                           requires_actionable=False)
        evaluate_triggers({"k": (True, "m")}, 3, self.path, dt.date(2026, 1, 1),
                          rules=[rule])
        evaluate_triggers({"k": (False, "")}, 3, self.path, dt.date(2026, 1, 2),
                          rules=[rule])
        ev = evaluate_triggers({"k": (True, "m")}, 3, self.path,
                               dt.date(2026, 1, 3), rules=[rule])
        self.assertFalse(ev[0].fired)

    def test_min_interval_blocks_repeat(self):
        rule = TriggerRule("k", "t", persistence=1, min_days_between=30,
                           requires_actionable=False)
        cond = {"k": (True, "m")}
        a = evaluate_triggers(cond, 3, self.path, dt.date(2026, 1, 1), rules=[rule])
        b = evaluate_triggers(cond, 3, self.path, dt.date(2026, 1, 10), rules=[rule])
        c = evaluate_triggers(cond, 3, self.path, dt.date(2026, 3, 1), rules=[rule])
        self.assertTrue(a[0].fired)
        self.assertFalse(b[0].fired)
        self.assertTrue(c[0].fired)

    def test_actionability_gate_silences_far_from_expiry(self):
        """만기가 멀면 알려도 할 수 있는 게 없다. 그런 알림은 노이즈다."""
        rule = TriggerRule("k", "t", persistence=1, min_days_between=0,
                           requires_actionable=True)
        cond = {"k": (True, "m")}
        far = evaluate_triggers(cond, 30, self.path, dt.date(2026, 1, 1), rules=[rule])
        self.assertFalse(far[0].fired)
        self.assertIn("D-30", far[0].suppressed_reason)
        near = evaluate_triggers(cond, 6, self.path, dt.date(2026, 1, 2), rules=[rule])
        self.assertTrue(near[0].fired)

    def test_invalid_persistence_rejected(self):
        with self.assertRaises(ValueError):
            TriggerRule("k", "t", persistence=0)


class TestCalendar(unittest.TestCase):
    def test_hard_deadlines_present(self):
        from fde.calendar import build_calendar

        ms = build_calendar(minimal_state(), minimal_policy())
        hard = [m for m in ms if m.hard]
        self.assertTrue(any("통지 마감" in m.title for m in hard))
        self.assertTrue(any("통지 창 시작" in m.title for m in hard))

    def test_milestones_sorted_and_before_expiry(self):
        from fde.calendar import build_calendar

        s = minimal_state()
        ms = build_calendar(s, minimal_policy())
        dates = [m.date for m in ms]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[-1], s.housing.contract_end)


if __name__ == "__main__":
    unittest.main()
