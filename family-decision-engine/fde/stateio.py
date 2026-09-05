"""family_state.yaml <-> FamilyState 변환 + 실행 스냅샷.

재현성이 핵심이다. 3개월 뒤 결론이 바뀌었을 때 그게 시장 변화 때문인지
내가 코드를 고쳤기 때문인지 구분할 수 없으면 시스템 전체의 신뢰가 무너진다.
그래서 모든 실행은 입력 스냅샷 + 해시를 runs/ 에 남긴다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from fde.models import (
    Assumptions,
    Asset,
    Budget,
    Candidate,
    Child,
    Debt,
    DepositRisk,
    Family,
    FamilyState,
    HousingCurrent,
    Person,
    Preferences,
    ValidationError,
)


def _date(v: Any) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def _build(cls, data: dict[str, Any] | None, *, path: str = ""):
    """dict -> dataclass. 알 수 없는 키는 오타일 가능성이 높으므로 에러."""
    data = data or {}
    if not isinstance(data, dict):
        raise ValidationError(f"{path or cls.__name__}: 매핑이어야 합니다 (받은 값: {data!r})")

    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValidationError(
            f"{path or cls.__name__}: 알 수 없는 키 {sorted(unknown)}. "
            f"사용 가능한 키: {sorted(known)}"
        )

    kwargs: dict[str, Any] = {}
    for name, f in known.items():
        if name not in data:
            continue
        raw = data[name]
        ftype = str(f.type)
        if "date" in ftype and "datetime" not in ftype:
            kwargs[name] = _date(raw)
        else:
            kwargs[name] = raw
    return cls(**kwargs)


def load_state(path: str | Path) -> FamilyState:
    p = Path(path)
    if not p.exists():
        raise ValidationError(
            f"상태 파일이 없습니다: {p}\n"
            f"config/family_state.example.yaml 을 복사해서 시작하세요."
        )
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    fam_doc = doc.get("family", {}) or {}
    family = Family(
        adults=[_build(Person, a, path=f"family.adults[{i}]")
                for i, a in enumerate(fam_doc.get("adults", []) or [])],
        children=[_build(Child, c, path=f"family.children[{i}]")
                  for i, c in enumerate(fam_doc.get("children", []) or [])],
        second_child_probability=fam_doc.get("second_child_probability", 0.0),
        second_child_expected_date=_date(fam_doc.get("second_child_expected_date")),
    )

    housing_doc = dict(doc.get("housing", {}) or {})
    risk_doc = housing_doc.pop("risk", {}) or {}
    housing = _build(HousingCurrent, housing_doc, path="housing")
    housing.risk = _build(DepositRisk, risk_doc, path="housing.risk")

    state = FamilyState(
        as_of=_date(doc.get("as_of")) or dt.date.today(),
        family=family,
        assets=[_build(Asset, a, path=f"assets[{i}]")
                for i, a in enumerate(doc.get("assets", []) or [])],
        debts=[_build(Debt, d, path=f"debts[{i}]")
               for i, d in enumerate(doc.get("debts", []) or [])],
        housing=housing,
        candidates=[_build(Candidate, c, path=f"candidates[{i}]")
                    for i, c in enumerate(doc.get("candidates", []) or [])],
        preferences=_build(Preferences, doc.get("preferences"), path="preferences"),
        assumptions=_build(Assumptions, doc.get("assumptions"), path="assumptions"),
        budget=_build(Budget, doc.get("budget"), path="budget"),
        bank_quotes=doc.get("bank_quotes", {}) or {},
    )
    return state


# ---------------------------------------------------------------- 스냅샷


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    return obj


def state_hash(state: FamilyState) -> str:
    blob = json.dumps(_jsonable(state), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def snapshot_run(
    state: FamilyState,
    policy_dir: str | Path,
    outputs: dict[str, str],
    runs_dir: str | Path = "runs",
    label: str = "",
) -> Path:
    """입력 + 출력 + 코드버전을 한 디렉터리에 봉인한다.

    이게 있어야 "3개월 전에는 왜 전세가 답이었는지"를 재현할 수 있다.
    """
    h = state_hash(state)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{h}" + (f"_{label}" if label else "")
    out = Path(runs_dir) / name
    out.mkdir(parents=True, exist_ok=True)

    (out / "state.json").write_text(
        json.dumps(_jsonable(state), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    pol = Path(policy_dir)
    if pol.exists():
        dest = out / "policy"
        dest.mkdir(exist_ok=True)
        for f in (pol.glob("*.yaml") if pol.is_dir() else [pol]):
            shutil.copy2(f, dest / f.name)

    for fname, content in outputs.items():
        (out / fname).write_text(content, encoding="utf-8")

    meta = {
        "run_id": name,
        "state_hash": h,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "as_of": state.as_of.isoformat(),
        "git_commit": _git_commit(),
    }
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def _git_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"
