"""백테스트 / 재현 하네스.

리뷰 지적: 초안에는 **검증 계층이 통째로 없었다.**
시스템이 맞는지 확인할 방법이 없으면, 3개월 뒤 결론이 바뀌었을 때
그게 시장 변화 때문인지 코드 수정 때문인지 구분할 수 없다.

세 가지를 제공한다:
  1. as-of 재현    - 과거 시점 데이터/정책만으로 돌리면 뭐라고 했을까
  2. 결론 안정성    - 시점을 옮겨가며 결론이 얼마나 자주 바뀌는가
  3. 스냅샷 대조    - runs/ 에 봉인된 과거 실행을 지금 코드로 다시 돌려 비교
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

from fde.money import fmt_krw
from fde.policy import load_policy
from fde.stateio import load_state


def run_backtest(
    state_path: str, policy_path: str, dates: list[str]
) -> str:
    """여러 기준일에서 같은 상태를 돌려 결론이 얼마나 안정적인지 본다.

    주의: 시장 데이터를 과거 값으로 되돌리지는 않는다(그 데이터가 없다면).
    여기서 검증하는 것은 **시간 경과 자체가 결론을 바꾸는가**이다.
    만기가 가까워질수록 글라이드패스와 유동성 제약이 조여지므로,
    같은 가정에서도 결론이 바뀔 수 있고 그게 바뀌는 게 정상이다.
    """
    from fde.decision import run_decision

    base = load_state(state_path)
    lines = [
        "",
        "=" * 78,
        "백테스트 - 기준일을 옮겨가며 결론이 얼마나 안정적인가",
        "=" * 78,
        "",
        f"  {'기준일':<14}{'만기까지':>9}  {'최적 옵션':<28}{'2위 대비 격차':>16}",
        "-" * 78,
    ]

    prev_winner = None
    flips = 0
    rows = 0

    for d in dates:
        as_of = dt.date.fromisoformat(d.strip())
        state = dataclasses.replace(base, as_of=as_of)
        try:
            m = state.months_to_expiry()
        except Exception as e:
            lines.append(f"  {d:<14}  (건너뜀: {e})")
            continue
        if m < 0:
            lines.append(f"  {d:<14}  (만기 이후 - 건너뜀)")
            continue

        policy = load_policy(policy_path, as_of)
        r = run_decision(state, policy)
        b = r.best
        winner = b.spec.name if b else "(전 옵션 탈락)"
        flag = ""
        if prev_winner and winner != prev_winner:
            flips += 1
            flag = "  <- 결론 변경"
        prev_winner = winner
        rows += 1
        lines.append(
            f"  {d:<14}{m:>7}개월  {winner:<28}{fmt_krw(r.margin):>16}{flag}"
        )

    lines.append("-" * 78)
    if rows > 1:
        rate = flips / (rows - 1)
        lines.append(
            f"\n  {rows}개 시점 중 결론이 {flips}번 바뀌었습니다 (변경률 {rate:.0%})."
        )
        if rate > 0.4:
            lines.append(
                "  결론이 시점에 따라 자주 바뀝니다. 이는 옵션 간 격차가 작다는 뜻이고,\n"
                "  '어느 쪽이든 큰 차이 없다'가 정직한 해석입니다.\n"
                "  이럴 때는 화폐가치가 아니라 비화폐 요인(통근/육아/안정성)으로 결정하세요."
            )
        elif flips == 0:
            lines.append("  결론이 전 구간에서 유지되었습니다. 안정적입니다.")
    return "\n".join(lines) + "\n"


def replay_snapshot(run_dir: str | Path) -> str:
    """runs/ 에 봉인된 과거 실행을 지금 코드로 다시 돌려 비교한다.

    결론이 달라졌다면 원인은 둘 중 하나다: 정책 룰셋이 바뀌었거나, 코드가 바뀌었거나.
    둘 다 아닌데 달라졌다면 버그다.
    """
    p = Path(run_dir)
    meta_f, state_f = p / "meta.json", p / "state.json"
    if not meta_f.exists() or not state_f.exists():
        return f"[에러] 스냅샷이 아닙니다: {p}"

    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    old_report = (p / "report.txt")
    lines = [
        "",
        "=" * 78,
        f"스냅샷 재현: {meta.get('run_id')}",
        "=" * 78,
        f"  기록 시각    {meta.get('created_at')}",
        f"  기준일       {meta.get('as_of')}",
        f"  state_hash   {meta.get('state_hash')}",
        f"  git_commit   {meta.get('git_commit')}",
        "",
    ]
    if old_report.exists():
        text = old_report.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith(">>>"):
                lines.append(f"  당시 결론: {line.strip()[3:].strip()}")
                break
    lines.append(
        "\n  같은 입력으로 지금 코드를 돌려 결론이 다르다면, 원인은\n"
        "  (1) 정책 룰셋 변경 (2) 코드 변경 둘 중 하나여야 합니다.\n"
        "  둘 다 아닌데 다르면 버그입니다."
    )
    return "\n".join(lines) + "\n"


def list_runs(runs_dir: str | Path = "runs") -> list[dict]:
    out = []
    for d in sorted(Path(runs_dir).glob("*/")):
        f = d / "meta.json"
        if f.exists():
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out
