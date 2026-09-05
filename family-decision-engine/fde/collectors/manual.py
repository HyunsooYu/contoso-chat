"""수동 입력 수집기.

입주물량은 공식 API가 없다. 초안이 이걸 금리·실거래가와 같은 급으로 나열한 건
낙관적이었다. 민간 집계를 손으로 CSV 에 넣거나 인허가·착공 통계로 역산해야 한다.

**출처를 CSV 주석으로 남기는 것을 강제한다.** 3개월 뒤 이 숫자가 어디서 왔는지
모르면 쓸 수 없다.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from fde.collectors.base import Collector, CollectResult
from fde.collectors.store import Observation, Store


class ManualSupplyCollector(Collector):
    name = "manual_supply"
    env_key = None

    def collect(self, store: Store, config: dict, **kw) -> CollectResult:
        path = Path(config.get("manual", {}).get("supply_csv", "data/supply.csv"))
        if not path.exists():
            msg = (
                f"{path} 없음. 입주물량은 공식 API가 없으므로 수동 입력이 필요합니다. "
                f"`python -m fde collect --init-supply` 로 템플릿을 만드세요."
            )
            store.log(self.name, "skipped", 0, msg)
            return CollectResult(self.name, "skipped", message=msg)

        text = path.read_text(encoding="utf-8")
        has_source = any(
            l.strip().startswith("#") and ("출처" in l or "source" in l.lower())
            for l in text.splitlines()
        )
        warnings: list[str] = []
        if not has_source:
            warnings.append(
                f"{path} 에 출처 주석이 없습니다. '# 출처: ...' 줄을 추가하세요. "
                f"출처 없는 숫자는 3개월 뒤 쓸 수 없습니다."
            )

        obs: list[Observation] = []
        rows = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
        for row in csv.DictReader(rows):
            try:
                ym = str(row["year_month"]).strip()
                d = dt.date(int(ym[:4]), int(ym[4:6]), 1)
                obs.append(Observation(
                    self.name, f"supply_{row['region_code'].strip()}",
                    d, float(row["units"]), "units",
                ))
            except Exception as e:
                warnings.append(f"행 파싱 실패: {row} ({e})")

        n = store.put_series(obs) if obs else 0
        store.log(self.name, "ok", n, str(path))
        return CollectResult(self.name, "ok", n, str(path), warnings[:5])


SUPPLY_TEMPLATE = """# 입주물량 수동 입력
# 출처: (여기에 반드시 적으세요 - 예: 부동산R114 2026-09 집계, 조회일 2026-09-05)
# 형식: region_code,year_month,units
region_code,year_month,units
41135,202601,1200
41135,202604,850
11710,202602,2100
"""


def init_supply_template(path: str | Path = "data/supply.csv") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(SUPPLY_TEMPLATE, encoding="utf-8")
    return p
