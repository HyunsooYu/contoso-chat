"""의사결정 엔진 - 3단 분리.

초안의 "전세 81점 / 매수 68점" 을 버리고 이렇게 한다:

  1단 하드 제약 (통과/탈락)  : 점수화 금지. DSR/자기자본/통근상한/유동성.
  2단 화폐화 가능 전부 (원)  : 여기서 순위가 나온다. 종료시점 세후 순자산.
  3단 화폐화 불가 잔여        : 사용자가 답한 WTP 로만 환산. 동점 처리용.

산출물은 "81점"이 아니라 이런 문장이다:
  "전세 연장이 매수 대비 4,200만원 유리. 단 이 결론은 전세보증금 상승률
   가정에 전적으로 의존하며 연 5.5% 이상이면 뒤집힌다."
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fde.budget import LivingCostPath, build_living_cost_path
from fde.housing import assess_deposit_risk
from fde.models import Candidate, FamilyState
from fde.options import BuildContext, OptionSpec, Path, build
from fde.policy import PolicySet
from fde.simulate import SimResult, simulate


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str


@dataclass
class Evaluation:
    spec: OptionSpec
    sim: SimResult
    gates: list[Gate] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def failed_gates(self) -> list[Gate]:
        return [g for g in self.gates if not g.passed]

    @property
    def score(self) -> float:
        """순위 기준. 점수가 아니라 원 단위 금액이다."""
        return self.sim.adjusted_net_worth


# ================================================================== 옵션 열거


def enumerate_options(
    state: FamilyState, semi_wolse_ratios: tuple[float, ...] = (0.5, 0.25)
) -> list[OptionSpec]:
    """비교 대상을 만든다.

    반전세를 이산 옵션이 아니라 deposit_ratio 연속변수로 두므로,
    전세대출금리 > 전월세전환율 구간에서 월세가 유리해지는 지점이 자동으로 드러난다.
    """
    specs: list[OptionSpec] = []
    if not state.candidates:
        return specs

    home = state.candidates[0]

    # A. 현재 전세 유지 (갱신요구권 행사)
    specs.append(OptionSpec(
        name=f"A. 전세유지({home.name})", kind="jeonse", candidate=home,
        deposit_ratio=1.0, is_move=False, use_renewal_right=True,
        label="갱신요구권 행사 - 증액 상한 적용",
    ))

    # B. 다른 전세로 이사
    for c in state.candidates[1:]:
        specs.append(OptionSpec(
            name=f"B. 전세이사({c.name})", kind="jeonse", candidate=c,
            deposit_ratio=1.0, is_move=True,
        ))

    # C. 반전세/월세 (연속변수)
    for c in state.candidates:
        for ratio in semi_wolse_ratios:
            tag = "반전세" if ratio >= 0.4 else "월세"
            specs.append(OptionSpec(
                name=f"C. {tag}{ratio:.0%}({c.name})", kind="wolse", candidate=c,
                deposit_ratio=ratio, is_move=(c is not home),
            ))

    # D. 매수
    for c in state.candidates:
        if c.price_buy > 0:
            specs.append(OptionSpec(
                name=f"D. 매수({c.name})", kind="buy", candidate=c, is_move=True,
            ))

    # E. 청약 대기 (무주택 유지) - 가장 싼 전세에 머무르며 옵션 보유
    cheapest = min(state.candidates, key=lambda c: c.price_jeonse or 9e18)
    specs.append(OptionSpec(
        name=f"E. 청약대기({cheapest.name})", kind="wait", candidate=cheapest,
        deposit_ratio=1.0, is_move=(cheapest is not home),
        label="무주택 유지 - 특별공급 자격 보존",
    ))

    return specs


# ================================================================== 게이트


def apply_gates(state: FamilyState, spec: OptionSpec, sim: SimResult) -> list[Gate]:
    p = state.preferences
    gates: list[Gate] = []

    gates.append(Gate(
        "실행가능",
        sim.feasible,
        sim.infeasible_reason or "자기자본·대출 한도 내에서 실행 가능",
    ))
    if not sim.feasible:
        return gates

    worst_commute = max(spec.candidate.commute_minutes.values(), default=0)
    gates.append(Gate(
        "통근상한",
        worst_commute <= p.max_commute_minutes,
        f"최장 편도 {worst_commute}분 (상한 {p.max_commute_minutes}분)",
    ))

    gates.append(Gate(
        "유동성",
        not sim.went_negative,
        (f"현금 고갈 발생 - 최대 페널티 차입 {sim.peak_penalty_debt:,.0f}원"
         if sim.went_negative
         else f"최저 현금잔고 {sim.min_liquid:,.0f}원"),
    ))

    gates.append(Gate(
        "비상금",
        sim.liquidity_breach_months == 0,
        (f"비상금({p.min_emergency_months}개월) 미달이 {sim.liquidity_breach_months}개월"
         if sim.liquidity_breach_months
         else "전 기간 비상금 유지"),
    ))

    gates.append(Gate(
        "주거비부담률",
        sim.max_housing_burden <= p.max_housing_burden_ratio,
        f"최대 {sim.max_housing_burden:.1%} (상한 {p.max_housing_burden_ratio:.0%}, 원금 제외)",
    ))

    gates.append(Gate(
        "총주거지출",
        sim.max_total_payment_ratio <= p.max_total_payment_ratio,
        f"최대 {sim.max_total_payment_ratio:.1%} (상한 {p.max_total_payment_ratio:.0%}, 원금 포함)",
    ))

    return gates


# ================================================================== 실행


@dataclass
class DecisionResult:
    evaluations: list[Evaluation]
    living: LivingCostPath
    decision_month: int
    deposit_delay_months: int
    warnings: list[str] = field(default_factory=list)

    @property
    def passing(self) -> list[Evaluation]:
        return sorted([e for e in self.evaluations if e.passed],
                      key=lambda e: e.score, reverse=True)

    @property
    def failing(self) -> list[Evaluation]:
        return [e for e in self.evaluations if not e.passed]

    @property
    def best(self) -> Evaluation | None:
        return self.passing[0] if self.passing else None

    @property
    def runner_up(self) -> Evaluation | None:
        p = self.passing
        return p[1] if len(p) > 1 else None

    @property
    def dominant_failure(self) -> str:
        """통과 옵션이 없을 때, 무엇이 전부를 막았는가.

        '전 옵션 탈락'은 이 시스템이 낼 수 있는 가장 중요한 출력이다.
        어떤 주거 선택으로도 해결되지 않는 문제가 있다는 뜻이기 때문이다.
        """
        if self.passing or not self.evaluations:
            return ""
        counts: dict[str, int] = {}
        for e in self.failing:
            for g in e.failed_gates:
                counts[g.name] = counts.get(g.name, 0) + 1
        if not counts:
            return ""
        top, n = max(counts.items(), key=lambda kv: kv[1])
        total = len(self.failing)
        sample = next(
            (g.detail for e in self.failing for g in e.failed_gates if g.name == top), ""
        )
        return f"{top} ({n}/{total} 옵션) - {sample}"

    @property
    def margin(self) -> float:
        """1위와 2위의 원 단위 격차. 이게 작으면 결론이 불안정하다는 뜻."""
        b, r = self.best, self.runner_up
        return (b.score - r.score) if (b and r) else 0.0


def run_decision(
    state: FamilyState,
    policy: PolicySet,
    path: Path | None = None,
    horizon: int | None = None,
    deposit_delay_months: int | None = None,
    deposit_recovery_ratio: float = 1.0,
    specs: list[OptionSpec] | None = None,
    living: LivingCostPath | None = None,
) -> DecisionResult:
    H = horizon or state.assumptions.horizon_months
    if path is None:
        # 기본 경로는 '성장 0'이 아니라 BASE 시나리오다. 포트폴리오 수익률을
        # 0으로 두면 현금을 쥐는 옵션(전세)이 부당하게 불리해진다.
        from fde.scenario import deterministic_scenarios, scenario_path

        base = deterministic_scenarios(state.assumptions)[0]
        path = scenario_path(base, state.assumptions, H)
    living = living or build_living_cost_path(state, policy, H)

    T = max(0, min(state.months_to_expiry(), H - 1))

    if deposit_delay_months is None:
        risk = assess_deposit_risk(state.housing, policy)
        deposit_delay_months = 0   # 기본 시나리오는 정상 반환. 지연은 시나리오에서 스트레스.
    delay = deposit_delay_months

    ctx = BuildContext(
        state=state, policy=policy, path=path, decision_month=T, horizon=H,
        deposit_return_month=T + delay,
        deposit_recovery_ratio=deposit_recovery_ratio,
    )

    specs = specs if specs is not None else enumerate_options(state)
    evals: list[Evaluation] = []
    for spec in specs:
        sch = build(ctx, spec)
        sim = simulate(state, policy, sch, path, living, H)
        evals.append(Evaluation(spec, sim, apply_gates(state, spec, sim)))

    warnings = [w.render() for w in policy.warnings()]
    return DecisionResult(evals, living, T, delay, warnings)
