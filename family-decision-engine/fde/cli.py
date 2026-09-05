"""CLI.

설계 원칙: 각 서브커맨드는 **혼자서도 쓸모 있어야 한다.**
전체 리포트를 돌리지 않아도 `fde calendar` 하나만으로 가치가 있어야 한다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

DEFAULT_STATE = "config/family_state.yaml"
DEFAULT_POLICY = "config/policy"
DEFAULT_DB = "market.db"
TRIGGER_STATE = "runs/.trigger_state.json"


def _load(args):
    from fde.policy import load_policy
    from fde.stateio import load_state

    state = load_state(args.state)
    as_of = dt.date.fromisoformat(args.as_of) if getattr(args, "as_of", None) else state.as_of
    if getattr(args, "as_of", None):
        import dataclasses
        state = dataclasses.replace(state, as_of=as_of)
    return state, load_policy(args.policy, as_of)


# ---------------------------------------------------------------- commands


def cmd_check(args) -> int:
    from fde.housing import assess_deposit_risk
    from fde.models import ValidationError

    try:
        state, policy = _load(args)
    except ValidationError as e:
        print(f"[에러] {e}")
        return 1

    print(f"\n상태 파일: {args.state}  (기준일 {state.as_of})")
    problems = state.validate()
    critical = [p for p in problems if p.startswith("[중대]")]
    other = [p for p in problems if not p.startswith("[중대]")]

    if critical:
        print("\n계산보다 먼저 해야 할 일:")
        for p in critical:
            print(f"  {p}")
    if other:
        print("\n입력 경고:")
        for p in other:
            print(f"  - {p}")
    if not problems:
        print("\n  문제 없음.")

    risk = assess_deposit_risk(state.housing, policy)
    print(f"\n보증금 회수 리스크: {risk.severity.upper()}")
    print(f"  만기 지연 확률 {risk.prob_delay:.0%}, 예상 지연 {risk.expected_delay_months:.0f}개월")
    for d in risk.drivers:
        print(f"  - {d}")
    if risk.actions:
        print("\n  조치:")
        for a in risk.actions:
            print(f"  {a}")
    return 0


def cmd_policy_check(args) -> int:
    from fde.policy import load_policy

    policy = load_policy(args.policy, dt.date.today())
    ws = policy.warnings(only_touched=False)
    ph = [w for w in ws if w.confidence == "placeholder"]
    uv = [w for w in ws if w.confidence == "unverified"]
    st = [w for w in ws if w.confidence == "verified"]

    print(f"\n정책 룰셋: {args.policy}")
    print(f"  예시값(교체 필수)  {len(ph)}개")
    print(f"  미확인             {len(uv)}개")
    print(f"  확인됐으나 오래됨  {len(st)}개")

    if ph:
        print("\n[교체 필수] 이 값들이 계산에 쓰이면 결과를 신뢰하면 안 됩니다:")
        for w in ph:
            print(f"  - {w.key}")
    if uv:
        print("\n[확인 권장]")
        for w in uv:
            print(f"  - {w.key}  ({w.source})")
    print(
        "\n확인한 항목은 해당 YAML 에서 confidence: verified 와 "
        "verified_on: YYYY-MM-DD 를 적어주세요."
    )
    return 0


def cmd_tradeoffs(args) -> int:
    from fde.tradeoffs import render_questionnaire

    print(render_questionnaire())
    return 0


def cmd_calendar(args) -> int:
    from fde.calendar import view_calendar

    state, policy = _load(args)
    cv = view_calendar(state, policy)
    print(f"\n전세 만기 {state.housing.contract_end} 기준 역산 캘린더")
    print("(★ = 놓치면 선택지가 사라지는 하드 데드라인)\n")
    for line in cv.render_lines():
        print(line)
    if cv.overdue_hard:
        print("\n[!!] 이미 지난 하드 데드라인:")
        for m in cv.overdue_hard:
            print(f"  {m.date}  {m.title}")
    return 0


def cmd_buckets(args) -> int:
    from fde.budget import build_living_cost_path
    from fde.buckets import build_buckets
    from fde.report import render_buckets

    state, policy = _load(args)
    living = build_living_cost_path(state, policy, state.assumptions.horizon_months)
    print(render_buckets(build_buckets(state, policy, living)))
    return 0


def cmd_budget(args) -> int:
    from fde.budget import build_living_cost_path
    from fde.money import fmt_krw

    state, policy = _load(args)
    H = state.assumptions.horizon_months
    lp = build_living_cost_path(state, policy, H)
    income = state.family.household_monthly_income()

    print(f"\n목표 생활비 - 육아비 계단 곡선 ({H}개월)")
    print(f"월 가구소득(현재) {fmt_krw(income)}\n")
    print(f"  {'시점':<8}{'단계':<46}{'월생활비':>12}{'육아비':>12}")
    print("-" * 78)
    for t, label, amt in lp.steps:
        d = state.as_of.replace(day=1)
        y, m = d.year + (d.month - 1 + t) // 12, (d.month - 1 + t) % 12 + 1
        print(f"  {y}-{m:02d}  {label:<46}{fmt_krw(amt):>12}{fmt_krw(lp.childcare[t]):>12}")
    print("-" * 78)

    big = max(lp.steps, key=lambda s: s[2])
    print(
        f"\n  최대 지출 구간: {big[1]}  월 {fmt_krw(big[2])}\n"
        f"  현재 대비 월 {fmt_krw(big[2] - lp.at(0))} 증가.\n"
        f"  그 시점의 주거비 여력이 그만큼 줄어듭니다. 지금 주거비를 정할 때\n"
        f"  현재 소득이 아니라 이 시점을 기준으로 잡으세요."
    )
    return 0


def cmd_decide(args) -> int:
    from fde.budget import build_living_cost_path
    from fde.buckets import build_buckets
    from fde.calendar import view_calendar
    from fde.decision import run_decision
    from fde.report import render_full
    from fde.scenario import (
        deterministic_scenarios, monte_carlo, scenario_path,
    )
    from fde.sensitivity import run_sensitivity
    from fde.stateio import snapshot_run, state_hash

    state, policy = _load(args)
    H = state.assumptions.horizon_months
    living = build_living_cost_path(state, policy, H)

    decision = run_decision(state, policy, living=living)

    sens = None if args.quick else run_sensitivity(state, policy)
    risks = None if args.quick else monte_carlo(state, policy, n_paths=args.paths)

    scen_rows = None
    if not args.quick:
        scen_rows = []
        for sc in deterministic_scenarios(state.assumptions):
            path = scenario_path(sc, state.assumptions, H)
            r = run_decision(
                state, policy, path=path, living=living,
                deposit_delay_months=sc.deposit_delay_months,
                deposit_recovery_ratio=sc.deposit_recovery_ratio,
            )
            b = r.best
            scen_rows.append((
                sc,
                b.spec.name if b else "(전 옵션 탈락)",
                b.sim.terminal_net_worth if b else float("nan"),
                "" if b else r.dominant_failure,
            ))

    allocation = build_buckets(state, policy, living)
    cal = view_calendar(state, policy)

    text = render_full(state, decision, sens, risks, scen_rows, allocation, cal,
                       n_paths=args.paths)
    print(text)

    if args.save:
        out = snapshot_run(state, args.policy, {"report.txt": text},
                           runs_dir="runs", label=args.label or "")
        print(f"\n[저장됨] {out}")
    return 0


def cmd_sensitivity(args) -> int:
    from fde.report import render_sensitivity
    from fde.sensitivity import price_threshold_for_buy, run_sensitivity

    state, policy = _load(args)
    print(render_sensitivity(run_sensitivity(state, policy)))
    print("\n  매수 임계가격 (부동산에 들고 갈 수 있는 숫자):")
    for i, c in enumerate(state.candidates):
        if c.price_buy > 0:
            _, msg = price_threshold_for_buy(state, policy, i)
            print(f"    - {msg}")
    return 0


def cmd_risk(args) -> int:
    from fde.decision import run_decision
    from fde.report import render_risk
    from fde.scenario import monte_carlo

    state, policy = _load(args)
    decision = run_decision(state, policy)
    risks = monte_carlo(state, policy, n_paths=args.paths)
    print(render_risk(risks, decision, state, args.paths))
    return 0


def cmd_triggers(args) -> int:
    from fde.budget import build_living_cost_path
    from fde.buckets import build_buckets
    from fde.calendar import view_calendar
    from fde.decision import run_decision
    from fde.housing import assess_deposit_risk
    from fde.money import fmt_krw
    from fde.sensitivity import run_sensitivity
    from fde.triggers import evaluate_triggers

    state, policy = _load(args)
    living = build_living_cost_path(state, policy, state.assumptions.horizon_months)
    al = build_buckets(state, policy, living)
    risk = assess_deposit_risk(state.housing, policy)
    cv = view_calendar(state, policy)
    sens = run_sensitivity(state, policy)
    decision = run_decision(state, policy, living=living)

    in_window = any(
        m.hard and m.category == "lease" and 0 <= (m.date - state.as_of).days <= 120
        for m in cv.milestones
    )
    conditions = {
        "deposit_risk_high": (
            risk.is_blocking or not state.housing.risk.hug_guaranteed,
            f"보증금 리스크 {risk.severity}" + (
                " / 반환보증 미가입" if not state.housing.risk.hug_guaranteed else ""),
        ),
        "renewal_window_open": (in_window, "갱신요구권 통지 창이 열려 있습니다."),
        "glide_path_breach": (
            al.risky_over_limit > 0,
            f"안전자산 {fmt_krw(al.risky_over_limit)} 부족 ({al.phase.name} 국면)",
        ),
        "threshold_approaching": (
            bool(sens.fragile),
            f"{sens.fragile[0].render()}" if sens.fragile else "",
        ),
        "conclusion_flipped": (False, ""),
        "affordability_worsened": (False, ""),
    }

    Path(TRIGGER_STATE).parent.mkdir(parents=True, exist_ok=True)
    events = evaluate_triggers(conditions, state.months_to_expiry(),
                               TRIGGER_STATE, state.as_of)
    print(f"\n트리거 평가 ({state.as_of}, 만기 D-{state.months_to_expiry()}개월)\n")
    fired = [e for e in events if e.fired]
    held = [e for e in events if not e.fired]
    if fired:
        for e in fired:
            print(f"  [발화] {e.label}")
            print(f"         {e.message}")
            print(f"         -> {e.action}\n")
    else:
        print("  발화된 트리거 없음.\n")
    if held:
        print("  보류(노이즈 억제):")
        for e in held:
            print(f"    - {e.label}: {e.suppressed_reason}")
    return 0


def cmd_collect(args) -> int:
    from fde.collectors import ALL_COLLECTORS, Store, init_supply_template, load_collector_config

    if args.init_supply:
        p = init_supply_template()
        print(f"템플릿 생성: {p}\n출처 주석을 반드시 채우세요.")
        return 0

    cfg = load_collector_config(args.collectors)
    store = Store(args.db)
    print(f"\n수집 시작 (db={args.db})\n")
    for c in ALL_COLLECTORS:
        r = c.collect(store, cfg)
        print("  " + r.render())
        for w in r.warnings:
            print(f"      ! {w}")
    print(
        "\n  참고: 일 단위 수집은 가치가 거의 없습니다. 만기 전에는 행동 공간이\n"
        "  거의 닫혀 있어 매일 수집해도 바뀌는 결정이 없습니다. 월 1회면 충분합니다."
    )
    return 0


def cmd_backtest(args) -> int:
    from fde.backtest import run_backtest

    print(run_backtest(args.state, args.policy, args.dates.split(",")))
    return 0


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fde",
        description="가족 주거·재무 의사결정 엔진",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "권장 순서:\n"
            "  1. fde check        - 등기부/보증보험/갱신권부터. 코드보다 먼저.\n"
            "  2. fde tradeoffs    - 배우자와 함께 지불의사 질문지 작성\n"
            "  3. fde policy-check - 예시값으로 남아 있는 정책 수치 교체\n"
            "  4. fde decide       - 전체 리포트\n"
        ),
    )
    p.add_argument("--state", default=DEFAULT_STATE)
    p.add_argument("--policy", default=DEFAULT_POLICY)
    p.add_argument("--as-of", default=None, help="기준일 재지정 (YYYY-MM-DD). 백테스트용.")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, fn, helptext in [
        ("check", cmd_check, "상태 검증 + 보증금 리스크 (가장 먼저 하세요)"),
        ("policy-check", cmd_policy_check, "교체해야 할 정책 수치 목록"),
        ("tradeoffs", cmd_tradeoffs, "부부 합의용 지불의사 질문지"),
        ("calendar", cmd_calendar, "만기 역산 체크리스트"),
        ("buckets", cmd_buckets, "현금 5버킷 + 글라이드패스"),
        ("budget", cmd_budget, "목표 생활비 + 육아비 계단 곡선"),
        ("sensitivity", cmd_sensitivity, "결론이 뒤집히는 임계값"),
        ("triggers", cmd_triggers, "트리거 평가 (히스테리시스)"),
    ]:
        s = sub.add_parser(name, help=helptext)
        s.set_defaults(func=fn)

    d = sub.add_parser("decide", help="전체 의사결정 리포트")
    d.add_argument("--paths", type=int, default=300, help="몬테카를로 경로 수")
    d.add_argument("--quick", action="store_true", help="민감도/MC 생략 (빠름)")
    d.add_argument("--save", action="store_true", help="runs/ 에 스냅샷 저장")
    d.add_argument("--label", default="", help="스냅샷 라벨")
    d.set_defaults(func=cmd_decide)

    r = sub.add_parser("risk", help="몬테카를로 하방 리스크")
    r.add_argument("--paths", type=int, default=500)
    r.set_defaults(func=cmd_risk)

    c = sub.add_parser("collect", help="시장 데이터 수집 (월 1회면 충분)")
    c.add_argument("--db", default=DEFAULT_DB)
    c.add_argument("--collectors", default="config/collectors.yaml")
    c.add_argument("--init-supply", action="store_true", help="입주물량 CSV 템플릿 생성")
    c.set_defaults(func=cmd_collect)

    b = sub.add_parser("backtest", help="과거 시점 재현 - 그때 이 엔진은 뭐라 했을까")
    b.add_argument("--dates", required=True, help="쉼표구분 YYYY-MM-DD")
    b.set_defaults(func=cmd_backtest)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"[에러] 파일을 찾을 수 없습니다: {e}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
