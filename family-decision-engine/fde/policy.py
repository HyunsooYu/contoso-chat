"""정책/세제 룰셋 - 코드가 아니라 데이터.

설계 원칙 3가지:

1. **effective-dated**: 모든 룰은 `effective_from` 을 갖고, 엔진은 "as-of 날짜"를
   받아 그 시점에 유효했던 룰을 고른다. 과거 시점 백테스트가 가능해진다.

2. **검증 추적**: 모든 룰은 `confidence` 와 `verified_on` 을 갖는다.
   LTV/DSR/취득세/특례대출 요건은 수시로 바뀌므로, 검증되지 않은 값이
   **결과에 실제로 영향을 준 경우** 리포트에 반드시 경고로 노출된다.
   이 프로젝트는 검증 안 된 숫자로 조용히 확신을 주는 것을 최대 실패로 본다.

3. **stale 감지**: verified_on 이 오래되면 자동으로 stale 경고.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

STALE_AFTER_DAYS = 180

CONFIDENCE_LEVELS = ("verified", "unverified", "placeholder")


class PolicyError(Exception):
    pass


@dataclass
class Rule:
    """단일 정책 값."""

    key: str
    value: Any
    effective_from: dt.date
    effective_to: dt.date | None = None
    confidence: str = "placeholder"
    verified_on: dt.date | None = None
    source: str = ""
    note: str = ""

    def active_on(self, as_of: dt.date) -> bool:
        if as_of < self.effective_from:
            return False
        if self.effective_to is not None and as_of > self.effective_to:
            return False
        return True

    def is_stale(self, as_of: dt.date) -> bool:
        if self.confidence != "verified":
            return True
        if self.verified_on is None:
            return True
        return (as_of - self.verified_on).days > STALE_AFTER_DAYS


@dataclass
class PolicyWarning:
    key: str
    confidence: str
    verified_on: dt.date | None
    reason: str
    source: str = ""

    def render(self) -> str:
        when = self.verified_on.isoformat() if self.verified_on else "미검증"
        src = f" | 출처: {self.source}" if self.source else ""
        return f"[{self.confidence}] {self.key} (최종확인 {when}) - {self.reason}{src}"


class PolicySet:
    """as-of 날짜로 조회하는 룰셋. 조회된 키를 기록해 경고를 만든다."""

    def __init__(self, rules: dict[str, list[Rule]], as_of: dt.date):
        self._rules = rules
        self.as_of = as_of
        self._touched: set[str] = set()

    # ---- 조회 -------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        rule = self._resolve(key)
        if rule is None:
            if default is not None:
                return default
            raise PolicyError(
                f"정책 키 없음: {key!r} (as_of={self.as_of}). "
                f"config/policy/*.yaml 에 추가하세요."
            )
        self._touched.add(key)
        return rule.value

    def _resolve(self, key: str) -> Rule | None:
        candidates = [r for r in self._rules.get(key, []) if r.active_on(self.as_of)]
        if not candidates:
            return None
        # 여러 개면 가장 최근 발효
        return max(candidates, key=lambda r: r.effective_from)

    def has(self, key: str) -> bool:
        return self._resolve(key) is not None

    # ---- 경고 -------------------------------------------------------

    def warnings(self, only_touched: bool = True) -> list[PolicyWarning]:
        """결과에 실제로 사용된 룰 중 검증이 안 됐거나 오래된 것."""
        keys = sorted(self._touched) if only_touched else sorted(self._rules)
        out: list[PolicyWarning] = []
        for key in keys:
            rule = self._resolve(key)
            if rule is None or not rule.is_stale(self.as_of):
                continue
            if rule.confidence == "placeholder":
                reason = "예시값입니다. 실제 결정에 쓰기 전 반드시 실제 값으로 교체하세요."
            elif rule.confidence == "unverified":
                reason = "출처 확인이 안 된 값입니다."
            else:
                days = (self.as_of - rule.verified_on).days if rule.verified_on else -1
                reason = f"확인한 지 {days}일 지났습니다. 제도가 바뀌었을 수 있습니다."
            out.append(
                PolicyWarning(key, rule.confidence, rule.verified_on, reason, rule.source)
            )
        return out

    def blocking_warnings(self) -> list[PolicyWarning]:
        """placeholder 가 실제로 쓰인 경우 - 이건 결과를 신뢰하면 안 되는 수준."""
        return [w for w in self.warnings() if w.confidence == "placeholder"]

    @property
    def touched(self) -> set[str]:
        return set(self._touched)

    def reset_touched(self) -> None:
        self._touched.clear()


# ---------------------------------------------------------------- 로딩


def _as_date(v: Any) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def _flatten(prefix: str, node: Any, out: dict[str, list[Rule]], defaults: dict) -> None:
    """중첩 dict 를 dotted key 로 편다.

    리프 판정: dict 이면서 'value' 키를 가지면 룰, 아니면 계속 내려간다.
    """
    if isinstance(node, dict) and "value" in node:
        rule = Rule(
            key=prefix,
            value=node["value"],
            effective_from=_as_date(node.get("effective_from"))
            or defaults.get("effective_from")
            or dt.date(1900, 1, 1),
            effective_to=_as_date(node.get("effective_to")),
            confidence=node.get("confidence", defaults.get("confidence", "placeholder")),
            verified_on=_as_date(node.get("verified_on")) or defaults.get("verified_on"),
            source=node.get("source", defaults.get("source", "")),
            note=node.get("note", ""),
        )
        if rule.confidence not in CONFIDENCE_LEVELS:
            raise PolicyError(
                f"{prefix}: confidence 는 {CONFIDENCE_LEVELS} 중 하나여야 합니다 "
                f"(받은 값: {rule.confidence!r})"
            )
        out.setdefault(prefix, []).append(rule)
        return

    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("_"):
                continue
            _flatten(f"{prefix}.{k}" if prefix else k, v, out, defaults)
        return

    # 룰 래핑 없이 그냥 쓴 스칼라 - placeholder 로 취급
    out.setdefault(prefix, []).append(
        Rule(
            key=prefix,
            value=node,
            effective_from=defaults.get("effective_from") or dt.date(1900, 1, 1),
            confidence="placeholder",
            note="value/confidence 래핑 없이 작성된 값",
        )
    )


def load_policy(path: str | Path, as_of: dt.date | None = None) -> PolicySet:
    """정책 YAML 디렉터리 또는 단일 파일을 읽는다."""
    p = Path(path)
    files = sorted(p.glob("*.yaml")) if p.is_dir() else [p]
    if not files:
        raise PolicyError(f"정책 파일이 없습니다: {p}")

    rules: dict[str, list[Rule]] = {}
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        defaults = {
            "effective_from": _as_date(doc.get("_defaults", {}).get("effective_from")),
            "verified_on": _as_date(doc.get("_defaults", {}).get("verified_on")),
            "confidence": doc.get("_defaults", {}).get("confidence", "placeholder"),
            "source": doc.get("_defaults", {}).get("source", ""),
        }
        body = {k: v for k, v in doc.items() if not k.startswith("_")}
        _flatten("", body, rules, defaults)

    return PolicySet(rules, as_of or dt.date.today())
