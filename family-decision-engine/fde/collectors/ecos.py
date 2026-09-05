"""한국은행 ECOS 금리 수집."""
from __future__ import annotations

import datetime as dt

from fde.collectors.base import Collector, CollectResult, api_key
from fde.collectors.store import Observation, Store


def _parse_ecos_date(s: str) -> dt.date:
    s = s.strip()
    if len(s) == 8:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if len(s) == 6:
        return dt.date(int(s[:4]), int(s[4:6]), 1)
    return dt.date(int(s[:4]), 1, 1)


class EcosCollector(Collector):
    name = "ecos"
    env_key = "ECOS_API_KEY"

    def collect(
        self, store: Store, config: dict, years: int = 10, timeout: int = 20
    ) -> CollectResult:
        ok, why = self.available()
        if not ok:
            return CollectResult(self.name, "skipped", message=why)

        import requests

        cfg = config.get("ecos", {})
        base = cfg.get("base_url", "")
        key = api_key(self.env_key)
        today = dt.date.today()
        start = f"{today.year - years}01"
        end = f"{today.year}{today.month:02d}"

        total = 0
        warnings: list[str] = []
        for s in cfg.get("series", []):
            url = (
                f"{base}/{key}/json/kr/1/1000/"
                f"{s['stat_code']}/{s.get('cycle', 'M')}/{start}/{end}/"
                f"{s.get('item_code', '')}"
            )
            try:
                r = requests.get(url, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                rows = data.get("StatisticSearch", {}).get("row", [])
                if not rows:
                    warnings.append(f"{s['key']}: 응답에 데이터 없음 (통계코드 확인 필요)")
                    continue
                obs = [
                    Observation(
                        self.name, s["key"], _parse_ecos_date(row["TIME"]),
                        float(row["DATA_VALUE"]) / 100.0, "ratio",
                    )
                    for row in rows if row.get("DATA_VALUE") not in (None, "")
                ]
                total += store.put_series(obs)
            except Exception as e:
                warnings.append(f"{s['key']}: {type(e).__name__} {e}")

        status = "ok" if total else "error"
        msg = f"{len(cfg.get('series', []))}개 시계열"
        if warnings:
            msg += f" (실패 {len(warnings)}건)"
        store.log(self.name, status, total, msg)
        return CollectResult(self.name, status, total, msg, warnings[:5])
