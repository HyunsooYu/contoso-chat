"""시뮬레이터 회계 항등식.

이 파일이 이 프로젝트에서 가장 중요한 테스트다.

원금 상환·보증금 납입/회수·대출 실행/상환은 전부 **잔액 이동**이므로
순자산에 영향을 주면 안 된다. 순자산을 바꾸는 것은 소비성 지출과 소득뿐이다.

이 항등식이 깨지면 "매수 vs 전세" 비교 전체가 무의미해진다.
"""
from __future__ import annotations

import unittest

from fde.budget import build_living_cost_path
from fde.options import BuildContext, OptionSpec, Path, build
from fde.simulate import simulate
from tests.helpers import minimal_policy, minimal_state


def _run(spec: OptionSpec, state=None, policy=None, horizon=36, delay=0, recovery=1.0):
    state = state or minimal_state()
    policy = policy or minimal_policy()
    path = Path.flat(horizon, monthly_portfolio_return=0.0)
    living = build_living_cost_path(state, policy, horizon)
    T = state.months_to_expiry()
    ctx = BuildContext(state, policy, path, T, horizon, T + delay, recovery)
    sch = build(ctx, spec)
    return sch, simulate(state, policy, sch, path, living, horizon), living, T


class TestAccountingIdentity(unittest.TestCase):
    """무성장·무수익·무세금 조건에서 순자산 항등식이 정확히 성립해야 한다."""

    def _identity(self, spec, **kw):
        state = kw.pop("state", None) or minimal_state()
        policy = kw.pop("policy", None) or minimal_policy()
        horizon = kw.pop("horizon", 36)
        sch, sim, living, T = _run(spec, state, policy, horizon, **kw)
        self.assertTrue(sim.feasible, sim.infeasible_reason)

        initial_nw = state.liquid_assets() + state.housing.deposit - state.total_debt()
        consumed = sum(
            m.housing_consumption + m.housing_one_off for m in sim.ledger
        )
        earned = sum(m.income - m.living for m in sim.ledger)
        expected = initial_nw + earned - consumed
        self.assertAlmostEqual(
            sim.terminal_net_worth, expected, delta=2.0,
            msg=(f"{spec.name}: 순자산 항등식 위반. "
                 f"실제 {sim.terminal_net_worth:,.0f} vs 기대 {expected:,.0f}"),
        )
        return sim

    def test_jeonse_stay(self):
        home = minimal_state().candidates[0]
        self._identity(OptionSpec("stay", "jeonse", home, 1.0, False, True))

    def test_jeonse_move(self):
        home = minimal_state().candidates[0]
        self._identity(OptionSpec("move", "jeonse", home, 1.0, True, False))

    def test_semi_wolse(self):
        home = minimal_state().candidates[0]
        self._identity(OptionSpec("semi", "wolse", home, 0.4, True, False))

    def test_buy_all_cash(self):
        home = minimal_state().candidates[0]
        self._identity(OptionSpec("buy", "buy", home, is_move=True))

    def test_buy_with_mortgage(self):
        """대출을 낀 매수에서도 항등식이 성립해야 한다."""
        state = minimal_state()
        state.candidates[0].price_buy = 800_000_000     # 자기자본 초과 -> 대출 발생
        sim = self._identity(OptionSpec("buy", "buy", state.candidates[0],
                                        is_move=True), state=state)
        self.assertGreater(sum(m.housing_principal for m in sim.ledger), 0.0,
                           "대출을 냈는데 원금상환이 잡히지 않았다")

    def test_deposit_delay_is_wealth_neutral_without_penalty(self):
        """페널티 차입 비용이 0이면 보증금 지연은 순자산을 바꾸지 않는다.

        지연 자체는 유동성 문제이지 부(富)의 손실이 아니다.
        """
        home = minimal_state().candidates[0]
        spec = OptionSpec("stay", "jeonse", home, 1.0, False, True)
        _, base, _, _ = _run(spec)
        _, delayed, _, _ = _run(spec, delay=6)
        self.assertAlmostEqual(base.terminal_net_worth,
                               delayed.terminal_net_worth, delta=2.0)

    def test_deposit_delay_costs_money_when_bridging(self):
        """현금이 모자라 페널티 차입을 하면 지연이 실제 비용이 된다.

        이것이 A-1 리스크가 결과에 물리는 지점이다.
        """
        import dataclasses

        state = minimal_state()
        state.assumptions = dataclasses.replace(state.assumptions,
                                                penalty_borrow_rate=0.09)
        home = state.candidates[0]
        spec = OptionSpec("stay", "jeonse", home, 1.0, False, True)
        _, base, _, _ = _run(spec, state=state)
        _, delayed, _, _ = _run(spec, state=state, delay=6)
        self.assertLess(delayed.terminal_net_worth, base.terminal_net_worth)
        self.assertTrue(delayed.went_negative)
        self.assertGreater(delayed.peak_penalty_debt, 0.0)

    def test_deposit_loss_reduces_wealth_by_exact_amount(self):
        home = minimal_state().candidates[0]
        state = minimal_state()
        spec = OptionSpec("stay", "jeonse", home, 1.0, False, True)
        _, base, _, _ = _run(spec, state=state)
        _, lost, _, _ = _run(spec, state=state, recovery=0.9)
        loss = state.housing.deposit * 0.10
        self.assertAlmostEqual(base.terminal_net_worth - lost.terminal_net_worth,
                               loss, delta=2.0)


class TestClassification(unittest.TestCase):
    def test_lump_repayment_not_counted_as_monthly_burden(self):
        """기존 전세대출 일시상환이 월 부담률에 섞이면 안 된다.

        이걸 섞으면 부담률이 1600% 같은 값이 나오고 모든 옵션이 탈락한다.
        (실제로 개발 중 발생했던 버그)
        """
        from fde.models import Debt

        state = minimal_state()
        state.debts = [Debt("jeonse_loan", 150_000_000, 0.0, 24,
                            kind="bullet", is_jeonse_loan=True)]
        home = state.candidates[0]
        spec = OptionSpec("stay", "jeonse", home, 1.0, False, True)
        _, sim, _, _ = _run(spec, state=state)
        self.assertLess(sim.max_total_payment_ratio, 1.0,
                        "일시상환이 월 부담률로 새어 들어갔다")

    def test_principal_excluded_from_housing_cost_npv(self):
        """원금 상환은 비용이 아니므로 npv_housing_cost 에 들어가면 안 된다."""
        state = minimal_state()
        state.candidates[0].price_buy = 800_000_000
        _, sim, _, _ = _run(OptionSpec("buy", "buy", state.candidates[0],
                                       is_move=True), state=state)
        total_principal = sum(m.housing_principal for m in sim.ledger)
        self.assertGreater(total_principal, 0)
        self.assertLess(sim.npv_housing_cost, total_principal,
                        "원금이 비용 NPV 에 섞여 있다")


class TestRenewalRight(unittest.TestCase):
    def test_cap_binds_when_market_jumps(self):
        """갱신요구권이 살아 있으면 시세가 급등해도 상한까지만 낸다."""
        from fde.housing import renewal_deposit

        policy = minimal_policy()
        capped, why = renewal_deposit(300_000_000, 400_000_000, True, policy)
        self.assertAlmostEqual(capped, 315_000_000, delta=1.0)
        self.assertIn("상한", why)

        market, _ = renewal_deposit(300_000_000, 400_000_000, False, policy)
        self.assertAlmostEqual(market, 400_000_000, delta=1.0)

    def test_market_below_cap_uses_market(self):
        from fde.housing import renewal_deposit

        amt, _ = renewal_deposit(300_000_000, 305_000_000, True, minimal_policy())
        self.assertAlmostEqual(amt, 305_000_000, delta=1.0)

    def test_renewal_right_has_no_value_at_zero_opportunity_cost(self):
        """기회비용이 0이면 갱신요구권에 금전적 가치가 없다.

        보증금을 더 내도 만기에 전액 회수되고, 그 사이 그 돈이 벌 수 있었던
        것도 없기 때문이다. 이건 모델이 맞는 것이지 버그가 아니다.
        갱신권의 가치는 '묶인 돈의 기회비용'과 '전세대출 이자'에서 나온다.
        """
        a, b = self._pair_with_and_without_right(jeonse_loan_rate=0.0,
                                                 portfolio_return=0.0)
        self.assertAlmostEqual(a, b, delta=2.0)

    def test_renewal_right_has_value_when_capital_has_a_price(self):
        """전세대출 금리가 있으면 갱신요구권이 실제 순자산 차이를 만든다."""
        a, b = self._pair_with_and_without_right(jeonse_loan_rate=0.04,
                                                 portfolio_return=0.0)
        self.assertGreater(a, b, "갱신요구권이 순자산에 반영되지 않았다")

    def _pair_with_and_without_right(self, **assump):
        import dataclasses

        results = []
        for used in (False, True):
            st = minimal_state()
            st.candidates[0].price_jeonse = 400_000_000     # 시세 급등
            st.housing.renewal_right_used = used
            st.assets[0].amount = 50_000_000                # 현금 부족 -> 대출 필요
            st.assumptions = dataclasses.replace(st.assumptions, **assump)
            spec = OptionSpec("stay", "jeonse", st.candidates[0], 1.0, False, True)
            _, sim, _, _ = _run(spec, state=st)
            results.append(sim.terminal_net_worth)
        return results[0], results[1]      # (갱신권 보유, 소진)


if __name__ == "__main__":
    unittest.main()
