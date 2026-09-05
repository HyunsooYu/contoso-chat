"""시장 데이터 저장소 - SQLite.

Postgres 를 쓰지 않는 이유: 사용자 1명, 데이터 수십 MB. 2년 뒤 재사용 시
살아 있어야 하는데, 의존성이 많을수록 그때 깨져 있을 확률이 높다.
stdlib 의 sqlite3 만 쓰면 파이썬만 있으면 동작한다.

모든 관측치는 출처(source)와 수집 시각(fetched_at)을 함께 저장한다.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    source      TEXT NOT NULL,
    key         TEXT NOT NULL,
    obs_date    TEXT NOT NULL,
    value       REAL NOT NULL,
    unit        TEXT DEFAULT '',
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, key, obs_date)
);

CREATE TABLE IF NOT EXISTS deals (
    source        TEXT NOT NULL,
    region_code   TEXT NOT NULL,
    deal_kind     TEXT NOT NULL,      -- trade | jeonse | wolse
    deal_date     TEXT NOT NULL,
    complex_name  TEXT,
    area_m2       REAL,
    floor         INTEGER,
    price         REAL,               -- 매매가 또는 보증금 (원)
    monthly_rent  REAL DEFAULT 0,     -- 원
    build_year    INTEGER,
    cancelled     INTEGER DEFAULT 0,
    direct_deal   INTEGER DEFAULT 0,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (source, region_code, deal_kind, deal_date, complex_name, area_m2, floor, price)
);

CREATE INDEX IF NOT EXISTS idx_deals_lookup
    ON deals (region_code, deal_kind, deal_date);

CREATE TABLE IF NOT EXISTS collection_log (
    run_at      TEXT NOT NULL,
    collector   TEXT NOT NULL,
    status      TEXT NOT NULL,
    rows        INTEGER DEFAULT 0,
    message     TEXT DEFAULT ''
);
"""


@dataclass
class Observation:
    source: str
    key: str
    obs_date: dt.date
    value: float
    unit: str = ""


@dataclass
class Deal:
    source: str
    region_code: str
    deal_kind: str
    deal_date: dt.date
    complex_name: str
    area_m2: float
    floor: int
    price: float
    monthly_rent: float = 0.0
    build_year: int = 0
    cancelled: bool = False
    direct_deal: bool = False


class Store:
    def __init__(self, path: str | Path = "market.db"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- 쓰기 -------------------------------------------------------

    def put_series(self, obs: list[Observation]) -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        rows = [
            (o.source, o.key, o.obs_date.isoformat(), float(o.value), o.unit, now)
            for o in obs
        ]
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO series "
                "(source,key,obs_date,value,unit,fetched_at) VALUES (?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def put_deals(self, deals: list[Deal]) -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        rows = [
            (d.source, d.region_code, d.deal_kind, d.deal_date.isoformat(),
             d.complex_name, d.area_m2, d.floor, d.price, d.monthly_rent,
             d.build_year, int(d.cancelled), int(d.direct_deal), now)
            for d in deals
        ]
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO deals (source,region_code,deal_kind,deal_date,"
                "complex_name,area_m2,floor,price,monthly_rent,build_year,cancelled,"
                "direct_deal,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def log(self, collector: str, status: str, rows: int = 0, message: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO collection_log (run_at,collector,status,rows,message) "
                "VALUES (?,?,?,?,?)",
                (dt.datetime.now().isoformat(timespec="seconds"),
                 collector, status, rows, message),
            )

    # ---- 읽기 -------------------------------------------------------

    def latest(self, source: str, key: str) -> tuple[dt.date, float] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT obs_date, value FROM series WHERE source=? AND key=? "
                "ORDER BY obs_date DESC LIMIT 1",
                (source, key),
            ).fetchone()
        return (dt.date.fromisoformat(r["obs_date"]), r["value"]) if r else None

    def series(self, source: str, key: str) -> list[tuple[dt.date, float]]:
        with self._conn() as c:
            rs = c.execute(
                "SELECT obs_date, value FROM series WHERE source=? AND key=? "
                "ORDER BY obs_date",
                (source, key),
            ).fetchall()
        return [(dt.date.fromisoformat(r["obs_date"]), r["value"]) for r in rs]

    def deals(
        self, region_code: str, deal_kind: str,
        since: dt.date | None = None, include_dirty: bool = False,
    ) -> list[dict]:
        q = ("SELECT * FROM deals WHERE region_code=? AND deal_kind=?")
        params: list = [region_code, deal_kind]
        if since:
            q += " AND deal_date >= ?"
            params.append(since.isoformat())
        if not include_dirty:
            q += " AND cancelled=0 AND direct_deal=0"
        q += " ORDER BY deal_date"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def last_runs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r) for r in c.execute(
                    "SELECT * FROM collection_log ORDER BY run_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]
