"""수집기 공통.

원칙:
  - API 키가 없으면 **조용히 건너뛴다**. 시스템 전체가 멈추면 안 된다.
  - 네트워크 없이도 나머지 기능이 전부 동작해야 한다.
  - 포털 호가 크롤링은 하지 않는다. 약관 위반이고, 호가는 실거래가 아니라 노이즈다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CollectResult:
    collector: str
    status: str                    # ok | skipped | error
    rows: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        icon = {"ok": "OK  ", "skipped": "SKIP", "error": "FAIL"}[self.status]
        return f"[{icon}] {self.collector}: {self.rows}건 - {self.message}"


def load_collector_config(path: str | Path = "config/collectors.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def api_key(env_name: str) -> str | None:
    v = os.environ.get(env_name, "").strip()
    return v or None


class Collector:
    name = "base"
    env_key: str | None = None

    def available(self) -> tuple[bool, str]:
        if self.env_key and not api_key(self.env_key):
            return False, f"환경변수 {self.env_key} 미설정 - 건너뜁니다."
        return True, ""

    def collect(self, store, config: dict, **kw) -> CollectResult:
        raise NotImplementedError
