"""국토교통부 실거래가 수집 + 정제.

리뷰 지적을 그대로 구현했다:
  실거래가 자체에 함정이 있다. 신고 지연(최대 30일), 취소 거래, 특수관계 거래.
  **정제 없이 쓰면 최근 1개월 시세가 항상 왜곡된다.**

호가(포털)는 수집하지 않는다. 약관 위반이고, 호가는 실거래가 아니다.
"""
from __future__ import annotations

import datetime as dt
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from fde.collectors.base import Collector, CollectResult, api_key
from fde.collectors.store import Deal, Store

MAN = 10_000.0


def _text(node, tag: str, default: str = "") -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else default


def _num(node, tag: str, default: float = 0.0) -> float:
    raw = _text(node, tag).replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return default


class MolitCollector(Collector):
    name = "molit"
    env_key = "DATA_GO_KR_KEY"

    def collect(
        self, store: Store, config: dict, months: int = 12, timeout: int = 20
    ) -> CollectResult:
        ok, why = self.available()
        if not ok:
            return CollectResult(self.name, "skipped", message=why)

        import requests

        cfg = config.get("molit", {})
        base = cfg.get("base_url", "")
        eps = cfg.get("endpoints", {})
        regions = cfg.get("regions", [])
        key = api_key(self.env_key)

        total = 0
        warnings: list[str] = []
        today = dt.date.today()

        for region in regions:
            code = region["code"]
            for kind, ep_key in (("trade", "apt_trade"), ("rent", "apt_rent")):
                ep = eps.get(ep_key)
                if not ep:
                    continue
                for i in range(months):
                    y = today.year
                    m = today.month - i
                    while m <= 0:
                        m += 12
                        y -= 1
                    ym = f"{y}{m:02d}"
                    url = f"{base}/{ep}"
                    params = {
                        "serviceKey": key, "LAWD_CD": code,
                        "DEAL_YMD": ym, "numOfRows": "1000", "pageNo": "1",
                    }
                    try:
                        r = requests.get(url, params=params, timeout=timeout)
                        r.raise_for_status()
                        deals = self._parse(r.text, code, kind)
                    except Exception as e:  # 네트워크/스키마 변경 모두 여기로
                        warnings.append(f"{code}/{ym}/{kind}: {type(e).__name__} {e}")
                        continue
                    if deals:
                        total += store.put_deals(deals)

        status = "ok" if total else ("error" if warnings else "ok")
        msg = f"{len(regions)}개 지역 x {months}개월"
        if warnings:
            msg += f" (실패 {len(warnings)}건 - 엔드포인트/스키마 변경 가능성)"
        store.log(self.name, status, total, msg)
        return CollectResult(self.name, status, total, msg, warnings[:5])

    def _parse(self, xml: str, region_code: str, kind: str) -> list[Deal]:
        root = ET.fromstring(xml)
        items = root.iter("item")
        out: list[Deal] = []
        for it in items:
            year = int(_num(it, "dealYear") or _num(it, "년"))
            month = int(_num(it, "dealMonth") or _num(it, "월"))
            day = int(_num(it, "dealDay") or _num(it, "일") or 1)
            if not year or not month:
                continue
            try:
                d = dt.date(year, month, min(day, 28))
            except ValueError:
                continue

            name = _text(it, "aptNm") or _text(it, "아파트")
            area = _num(it, "excluUseAr") or _num(it, "전용면적")
            floor = int(_num(it, "floor") or _num(it, "층"))
            build_year = int(_num(it, "buildYear") or _num(it, "건축년도"))

            cancelled = bool(_text(it, "cdealType") or _text(it, "해제여부"))
            direct = "직거래" in (_text(it, "dealingGbn") or _text(it, "거래유형"))

            if kind == "trade":
                price = (_num(it, "dealAmount") or _num(it, "거래금액")) * MAN
                rent = 0.0
                dk = "trade"
            else:
                price = (_num(it, "deposit") or _num(it, "보증금액")) * MAN
                rent = (_num(it, "monthlyRent") or _num(it, "월세금액")) * MAN
                dk = "wolse" if rent > 0 else "jeonse"

            if price <= 0:
                continue
            out.append(Deal(
                source=self.name, region_code=region_code, deal_kind=dk,
                deal_date=d, complex_name=name, area_m2=area, floor=floor,
                price=price, monthly_rent=rent, build_year=build_year,
                cancelled=cancelled, direct_deal=direct,
            ))
        return out


# ================================================================== 정제


@dataclass
class PriceStat:
    region_code: str
    deal_kind: str
    n_raw: int
    n_used: int
    median: float
    mean: float
    p25: float
    p75: float
    as_of: dt.date
    reliable: bool
    notes: list[str]


def clean_price_stat(
    store: Store,
    region_code: str,
    deal_kind: str,
    cleaning: dict,
    area_min: float = 0.0,
    area_max: float = 1e9,
    window_months: int = 6,
    as_of: dt.date | None = None,
) -> PriceStat:
    """실거래가를 통계로 쓸 수 있게 정제한다.

    1. 신고 지연 구간(기본 30일) 제외 - 최근 데이터는 아직 다 안 들어왔다
    2. 취소 거래 제외
    3. 직거래 제외 (특수관계 가능성)
    4. 전용면적 범위로 한정 - 평형이 섞이면 중앙값이 무의미해진다
    5. MAD 기반 이상치 제거
    6. 표본이 너무 적으면 통계로 쓰지 않는다고 표시
    """
    as_of = as_of or dt.date.today()
    lag = int(cleaning.get("reporting_lag_days", 30))
    cutoff = as_of - dt.timedelta(days=lag)
    since = as_of - dt.timedelta(days=30 * window_months)

    include_dirty = not (
        cleaning.get("exclude_cancelled", True) and cleaning.get("exclude_direct_deals", True)
    )
    rows = store.deals(region_code, deal_kind, since=since, include_dirty=include_dirty)
    n_raw = len(rows)
    notes: list[str] = []

    rows = [r for r in rows if dt.date.fromisoformat(r["deal_date"]) <= cutoff]
    if n_raw and len(rows) < n_raw:
        notes.append(f"신고지연 {lag}일 구간에서 {n_raw - len(rows)}건 제외")

    before = len(rows)
    rows = [r for r in rows if area_min <= (r["area_m2"] or 0) <= area_max]
    if before != len(rows):
        notes.append(f"전용면적 범위 밖 {before - len(rows)}건 제외")

    prices = [r["price"] for r in rows if r["price"] > 0]
    if len(prices) >= 3:
        med = statistics.median(prices)
        devs = [abs(p - med) for p in prices]
        mad = statistics.median(devs) or 1.0
        thr = float(cleaning.get("mad_outlier_threshold", 3.5))
        kept = [p for p in prices if abs(p - med) / (1.4826 * mad) <= thr]
        if len(kept) < len(prices):
            notes.append(f"이상치 {len(prices) - len(kept)}건 제거 (MAD>{thr})")
        prices = kept

    min_n = int(cleaning.get("min_deals_for_stat", 5))
    reliable = len(prices) >= min_n
    if not reliable:
        notes.append(f"표본 {len(prices)}건 < 최소 {min_n}건 - 통계로 신뢰하지 마세요")

    if not prices:
        return PriceStat(region_code, deal_kind, n_raw, 0, float("nan"),
                         float("nan"), float("nan"), float("nan"),
                         as_of, False, notes)

    s = sorted(prices)
    def pct(q: float) -> float:
        k = (len(s) - 1) * q
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return PriceStat(
        region_code, deal_kind, n_raw, len(s),
        statistics.median(s), sum(s) / len(s), pct(0.25), pct(0.75),
        as_of, reliable, notes,
    )
