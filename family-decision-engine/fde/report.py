"""리포트 생성.

산출물의 형태가 이 시스템의 성패를 가른다.

**절대 하지 않는 것**: "매수 81점 / 전세 68점" 같은 점수판.
손으로 계산하면 불확실함이 몸으로 느껴지는데, 대시보드는 그 불확실성을 지운다.
소수점까지 나온 숫자는 그 자체로 설득력을 갖지만 입력이 추측이면 출력도 추측이다.

**대신 하는 것**: 원 단위 격차 + 그 결론이 뒤집히는 조건.
"""
from __future__ import annotations

import datetime as dt

from fde.buckets import Allocation
from fde.calendar import CalendarView
from fde.decision import DecisionResult
from fde.models import FamilyState
from fde.money import fmt_krw
from fde.scenario import OptionRisk, Scenario
from fde.sensitivity import SensitivityReport

RULE = "=" * 78
THIN = "-" * 78


def _h(title: str) -> str:
    return f"\n{RULE}\n{title}\n{RULE}"


def render_warnings(state: FamilyState, decision: DecisionResult) -> str:
    """리포트 최상단. 신뢰할 수 없는 결과를 신뢰하게 만드는 것이 최대 실패다."""
    out = [_h("0. 이 결과를 얼마나 믿을 수 있는가")]

    blocking = [w for w in decision.warnings if w.startswith("[placeholder]")]
    if blocking:
        out.append(
            "\n[!] 아래 정책값이 **예시값 그대로** 계산에 사용되었습니다.\n"
            "    실제 결정에 쓰기 전 반드시 확인해서 교체하세요.\n"
            "    (`python -m fde policy-check` 로 목록 확인)\n"
        )
        for w in blocking:
            out.append(f"    - {w}")
    other = [w for w in decision.warnings if not w.startswith("[placeholder]")]
    if other:
        out.append("\n  확인 필요:")
        for w in other:
            out.append(f"    - {w}")

    problems = state.validate()
    critical = [p for p in problems if p.startswith("[중대]")]
    if critical:
        out.append("\n[!!] 계산보다 먼저 해야 할 일:\n")
        for p in critical:
            out.append(f"    {p}")

    rest = [p for p in problems if not p.startswith("[중대]")]
    if rest:
        out.append("\n  입력 상태 경고:")
        for p in rest:
            out.append(f"    - {p}")

    if not blocking and not problems:
        out.append("\n  경고 없음. 정책값이 모두 확인되었고 입력도 완전합니다.")
    return "\n".join(out)


def render_state(state: FamilyState) -> str:
    f = state.family
    kids = ", ".join(
        f"{c.name} {c.age_months(state.as_of)}개월" for c in f.children
    ) or "없음"
    oldest = f.oldest()
    out = [
        _h("1. 현재 가족 상태"),
        "",
        f"  기준일          {state.as_of}",
        f"  자녀            {kids}",
    ]
    if oldest:
        out += [
            f"  초등 입학       {oldest.elementary_entry_date()}",
            f"  중학 배정       {oldest.middle_school_entry_date()}  "
            f"<- 학군의 진짜 변곡점",
        ]
    out += [
        f"  전세 만기       {state.housing.contract_end}  (D-{state.months_to_expiry()}개월)",
        f"  갱신요구권      {'이미 사용' if state.housing.renewal_right_used else '미사용 (행사 가능)'}",
        "",
        f"  순자산          {fmt_krw(state.net_worth())}",
        f"    유동자산      {fmt_krw(state.liquid_assets())}",
        f"    전세보증금    {fmt_krw(state.housing.deposit)}",
        f"    부채          {fmt_krw(state.total_debt())}",
        f"  위험자산        {fmt_krw(state.risky_assets())}",
        "",
        f"  월 가구소득     {fmt_krw(state.family.household_monthly_income())}",
        f"  월 생활비       {fmt_krw(state.budget.base_living_cost())}",
    ]
    return "\n".join(out)


def render_decision(decision: DecisionResult, state: FamilyState) -> str:
    out = [_h("2. 결론")]
    best, runner = decision.best, decision.runner_up

    if not best:
        out.append("\n  통과한 옵션이 없습니다. 하드 제약을 다시 보세요.")
    else:
        out.append(f"\n  >>> {best.spec.name}")
        if runner:
            out.append(
                f"\n  2위 '{runner.spec.name}' 대비 {fmt_krw(decision.margin)} 유리합니다."
            )
            rel = decision.margin / max(1.0, abs(best.score))
            if rel < 0.03:
                out.append(
                    "  [주의] 격차가 3% 미만입니다. 이 정도면 순위가 사실상 동률이고,\n"
                    "         가정을 조금만 바꿔도 뒤집힙니다. 아래 임계값을 반드시 보세요."
                )

    out.append(f"\n{THIN}")
    out.append(
        f"  {'옵션':<26}{'종료시점 순자산':>16}{'비화폐 편익':>14}{'합계':>16}"
    )
    out.append(THIN)
    for e in decision.passing:
        out.append(
            f"  {e.spec.name:<26}{fmt_krw(e.sim.terminal_net_worth):>16}"
            f"{fmt_krw(e.sim.nonmonetary_npv):>14}{fmt_krw(e.score):>16}"
        )

    if decision.failing:
        out.append(f"\n  탈락 (하드 제약 - 점수화하지 않음):")
        for e in decision.failing:
            g = e.failed_gates[0]
            out.append(f"    x {e.spec.name:<26} [{g.name}] {g.detail}")

    if state.preferences.answered_on is None:
        out.append(
            "\n  [!] preferences 미작성 상태라 '비화폐 편익'이 전부 0입니다.\n"
            "      통근/육아/학군의 가치가 완전히 무시되고 있습니다.\n"
            "      `python -m fde tradeoffs` 를 배우자와 함께 하세요."
        )
    return "\n".join(out)


def render_sensitivity(rep: SensitivityReport) -> str:
    out = [_h("3. 이 결론이 뒤집히는 조건  <- 이 시스템의 핵심 산출물")]
    out.append(f"\n  {rep.summary}\n")
    out.append(
        "  집값을 예측하지 않습니다. 대신 '몇 %를 넘으면 결론이 바뀌는가'를 계산합니다.\n"
        "  월 1회 5분이면 임계값을 넘었는지 확인할 수 있습니다.\n"
    )
    out.append(THIN)
    for t in rep.thresholds:
        mark = " !!" if t.within_plausible else "   "
        out.append(f" {mark} {t.render()}")
    out.append(THIN)
    if rep.fragile:
        out.append(
            f"\n  !! 표시는 현실적으로 일어날 수 있는 범위 안에서 결론이 뒤집힌다는 뜻입니다.\n"
            f"     {len(rep.fragile)}개 가정이 여기 해당합니다. 이 결론은 견고하지 않습니다."
        )
    else:
        out.append("\n  현실적 범위 안에서 뒤집히는 가정이 없습니다. 비교적 견고한 결론입니다.")
    return "\n".join(out)


def render_risk(risks: dict[str, OptionRisk], decision: DecisionResult,
                state: FamilyState, n_paths: int) -> str:
    out = [_h(f"4. 하방 리스크 (상관 몬테카를로 {n_paths}경로)")]
    out.append(
        "\n  금리 상승 + 자산가격 하락 + 소득 둔화는 따로 오지 않고 같이 옵니다.\n"
        "  독립 시나리오로는 이 꼬리가 보이지 않습니다.\n"
    )
    out.append(THIN)
    out.append(
        f"  {'옵션':<24}{'하위10%':>14}{'중앙값':>14}{'CVaR5%':>14}"
        f"{'강제이사':>9}{'비상금부족':>11}"
    )
    out.append(THIN)
    passing = {e.spec.name for e in decision.passing}
    for name, r in sorted(risks.items(), key=lambda kv: -(kv[1].p50 if kv[1].p50 == kv[1].p50 else -9e18)):
        if name not in passing or r.n == 0:
            continue
        out.append(
            f"  {name:<24}{fmt_krw(r.p10):>14}{fmt_krw(r.p50):>14}"
            f"{fmt_krw(r.cvar05):>14}{r.prob_forced_move:>8.0%}{r.prob_liquidity_breach:>10.0%}"
        )
    out.append(THIN)

    forced = [r.prob_forced_move for n, r in risks.items() if n in passing and r.n]
    if forced and max(forced) - min(forced) < 0.05 and max(forced) > 0.05:
        out.append(
            f"\n  [중요] 강제이사(현금 고갈) 확률이 모든 옵션에서 비슷합니다({min(forced):.0%}~{max(forced):.0%}).\n"
            f"         이 위험은 어떤 주거 선택을 해도 줄지 않는다는 뜻입니다.\n"
            f"         원인은 주거 선택이 아니라 **보증금 회수 리스크**이고,\n"
            f"         줄이는 방법은 옵션 비교가 아니라 반환보증 가입입니다."
        )
    return "\n".join(out)


def render_scenarios(rows: list) -> str:
    """rows: (Scenario, winner_name, terminal_nw, dominant_failure)"""
    out = [_h("5. 결정론 시나리오 (설명용)")]
    out.append(f"\n  {'시나리오':<18}{'최적 옵션':<28}{'종료 순자산':>16}")
    out.append(THIN)
    wiped: list = []
    for row in rows:
        sc, winner, nw = row[0], row[1], row[2]
        fail = row[3] if len(row) > 3 else ""
        out.append(f"  {sc.label:<18}{winner:<28}{fmt_krw(nw):>16}")
        if fail:
            wiped.append((sc, fail))
    out.append(THIN)

    if wiped:
        out.append(
            "\n  [!!] 아래 시나리오에서는 **어떤 주거 선택도 제약을 통과하지 못했습니다.**\n"
            "       이건 옵션 비교로 해결되는 문제가 아니라는 뜻입니다.\n"
        )
        for sc, fail in wiped:
            out.append(f"       - {sc.label}: {fail}")
        if any(s.name.startswith("DEPOSIT") for s, _ in wiped):
            out.append(
                "\n       보증금 시나리오에서 전 옵션이 탈락했다면, 지금 비교하고 있는\n"
                "       매수/전세/월세 중 무엇을 고르든 그 위험은 그대로 남습니다.\n"
                "       먼저 해결해야 할 것은 주거 선택이 아니라 **보증금 회수 안전장치**입니다.\n"
                "       (반환보증 가입 / 등기부 확인 / 감액 재계약 협상)"
            )

    for row in rows:
        sc = row[0]
        if sc.narrative and sc.name in ("STRESS", "DEPOSIT_DELAY", "DEPOSIT_LOSS"):
            out.append(f"\n  [{sc.label}] {sc.narrative}")
    return "\n".join(out)


def render_buckets(al: Allocation) -> str:
    out = [_h("6. 현금 배분")]
    out.append(f"\n  만기 D-{al.months_to_expiry}개월 | 국면: {al.phase.name}")
    out.append(f"  {al.phase.instruction}\n")
    for b in al.buckets:
        out.append(f"  {b.render()}")
    out.append("")
    out.append(f"  유동자산 {fmt_krw(al.total_liquid)}  "
               f"버킷 합계 {fmt_krw(al.total_target)}  "
               f"투자가능 {fmt_krw(al.investable)}")
    out.append("")
    for a in al.actions:
        out.append(f"  {a}")
    for w in al.warnings:
        out.append(f"\n  [!] {w}")
    return "\n".join(out)


def render_calendar(cv: CalendarView) -> str:
    out = [_h("7. 만기 역산 캘린더")]
    out.append(
        "\n  점수 알림보다 이 캘린더가 실제 가치가 큽니다.\n"
        "  ★ 표시는 놓치면 선택지 자체가 사라지는 하드 데드라인입니다.\n"
    )
    out.extend("  " + l for l in cv.render_lines())
    if cv.overdue_hard:
        out.append("\n  [!!] 하드 데드라인이 이미 지났습니다:")
        for m in cv.overdue_hard:
            out.append(f"       {m.title} ({m.date})")
    return "\n".join(out)


def render_footer(run_id: str, state_hash: str, git_commit: str) -> str:
    return "\n".join([
        _h("재현 정보"),
        "",
        f"  run_id        {run_id}",
        f"  state_hash    {state_hash}",
        f"  git_commit    {git_commit}",
        "",
        "  이 실행의 입력·정책·출력이 runs/ 에 봉인되어 있습니다.",
        "  3개월 뒤 결론이 바뀌었을 때, 시장이 변한 것인지 코드를 고친 것인지",
        "  구분할 수 있어야 시스템을 신뢰할 수 있습니다.",
    ])


def render_full(
    state: FamilyState,
    decision: DecisionResult,
    sens: SensitivityReport | None,
    risks: dict[str, OptionRisk] | None,
    scenarios: list[tuple[Scenario, str, float]] | None,
    allocation: Allocation | None,
    calendar: CalendarView | None,
    n_paths: int = 0,
) -> str:
    parts = [
        f"\n{RULE}\nFAMILY DECISION ENGINE  -  {dt.date.today()}\n{RULE}",
        render_warnings(state, decision),
        render_state(state),
        render_decision(decision, state),
    ]
    if sens:
        parts.append(render_sensitivity(sens))
    if risks:
        parts.append(render_risk(risks, decision, state, n_paths))
    if scenarios:
        parts.append(render_scenarios(scenarios))
    if allocation:
        parts.append(render_buckets(allocation))
    if calendar:
        parts.append(render_calendar(calendar))
    return "\n".join(parts) + "\n"
