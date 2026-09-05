"""트리거 - 히스테리시스 필수.

리뷰 지적: 점수 변화 알림("매수 점수 68 → 79")은 금방 노이즈가 되고,
노이즈가 되면 시스템 전체를 안 보게 된다. 그리고 만기가 18개월 남았으면
그 알림을 받아도 **할 수 있는 게 없다.**

그래서 세 가지 규칙을 강제한다:
  1. 임계 초과가 N회 연속 지속될 때만 발화 (일시적 변동 무시)
  2. 같은 방향 재알림 최소 간격
  3. **행동 가능한 것만** 알림 (만기 전 행동 공간이 닫혀 있으면 알리지 않는다)

상태는 JSON 파일에 남긴다. 그래야 "연속 N회"를 셀 수 있다.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class TriggerRule:
    key: str
    label: str
    persistence: int = 2            # 연속 몇 회 만족해야 발화
    min_days_between: int = 30      # 같은 트리거 재알림 최소 간격
    requires_actionable: bool = True
    action: str = ""

    def __post_init__(self) -> None:
        if self.persistence < 1:
            raise ValueError("persistence 는 1 이상이어야 합니다.")


DEFAULT_RULES = [
    TriggerRule(
        "deposit_risk_high", "보증금 회수 위험 상승", persistence=1, min_days_between=14,
        requires_actionable=False,
        action="등기부 재열람 + 보증보험 가입 가능 여부 확인. 이건 언제나 행동 가능합니다.",
    ),
    TriggerRule(
        "renewal_window_open", "갱신요구권 통지 창", persistence=1, min_days_between=7,
        requires_actionable=False,
        action="임대인에게 갱신 의사를 서면으로 통지하세요. 하드 데드라인입니다.",
    ),
    TriggerRule(
        "glide_path_breach", "글라이드패스 위반", persistence=2, min_days_between=21,
        requires_actionable=False,
        action="위험자산을 변동성 큰 순서로 현금화하세요.",
    ),
    TriggerRule(
        "conclusion_flipped", "결론 변경", persistence=3, min_days_between=45,
        requires_actionable=True,
        action="임계값을 넘어 최적 옵션이 바뀌었습니다. 근거를 확인하세요.",
    ),
    TriggerRule(
        "threshold_approaching", "임계값 근접", persistence=3, min_days_between=45,
        requires_actionable=True,
        action="결론이 뒤집히는 임계값에 근접했습니다. 후보지 조사를 시작하세요.",
    ),
    TriggerRule(
        "affordability_worsened", "매수 여력 악화", persistence=3, min_days_between=45,
        requires_actionable=True,
        action="대출 여력이 줄었습니다. 매수 후보 가격대를 낮춰 잡으세요.",
    ),
]


@dataclass
class TriggerEvent:
    key: str
    label: str
    fired_on: dt.date
    message: str
    action: str
    suppressed_reason: str = ""

    @property
    def fired(self) -> bool:
        return not self.suppressed_reason


@dataclass
class TriggerState:
    streaks: dict[str, int] = field(default_factory=dict)
    last_fired: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def load(path: str | Path) -> "TriggerState":
        p = Path(path)
        if not p.exists():
            return TriggerState()
        d = json.loads(p.read_text(encoding="utf-8"))
        return TriggerState(d.get("streaks", {}), d.get("last_fired", {}))

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                     encoding="utf-8")


def actionable_now(months_to_expiry: int) -> bool:
    """만기 전에 실제로 행동할 수 있는 구간인가.

    만기가 18개월 남았는데 "매수 점수가 올랐습니다" 알림을 받아도 할 수 있는 게
    없다. 계약을 깨고 나가면 위약금과 새 보증금 조달 문제가 생기고, 그건 어떤
    점수 상승으로도 못 덮는다.
    """
    return months_to_expiry <= 12


def evaluate_triggers(
    conditions: dict[str, tuple[bool, str]],
    months_to_expiry: int,
    state_path: str | Path,
    as_of: dt.date | None = None,
    rules: list[TriggerRule] | None = None,
) -> list[TriggerEvent]:
    """conditions: {rule_key: (조건충족 여부, 사람이 읽을 메시지)}"""
    as_of = as_of or dt.date.today()
    rules = rules or DEFAULT_RULES
    st = TriggerState.load(state_path)
    events: list[TriggerEvent] = []

    for rule in rules:
        met, message = conditions.get(rule.key, (False, ""))
        if not met:
            st.streaks[rule.key] = 0
            continue

        st.streaks[rule.key] = st.streaks.get(rule.key, 0) + 1
        streak = st.streaks[rule.key]

        ev = TriggerEvent(rule.key, rule.label, as_of, message, rule.action)

        if streak < rule.persistence:
            ev.suppressed_reason = (
                f"지속성 미달 ({streak}/{rule.persistence}회) - "
                f"일시적 변동일 수 있어 보류"
            )
        elif rule.requires_actionable and not actionable_now(months_to_expiry):
            ev.suppressed_reason = (
                f"만기 D-{months_to_expiry}개월 - 지금 알려도 취할 수 있는 행동이 "
                f"없어 보류 (D-12개월부터 발화)"
            )
        else:
            last = st.last_fired.get(rule.key)
            if last:
                days = (as_of - dt.date.fromisoformat(last)).days
                if days < rule.min_days_between:
                    ev.suppressed_reason = (
                        f"{days}일 전 발화 - 최소 간격 {rule.min_days_between}일 미달"
                    )
            if ev.fired:
                st.last_fired[rule.key] = as_of.isoformat()

        events.append(ev)

    st.save(state_path)
    return events
