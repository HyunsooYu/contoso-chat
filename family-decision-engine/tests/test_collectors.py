"""수집기 - 네트워크 없이 검증한다."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fde.collectors import Deal, Observation, Store, clean_price_stat
from fde.collectors.base import Collector
from fde.collectors.manual import ManualSupplyCollector, init_supply_template
from fde.collectors.molit import MolitCollector

CLEANING = {
    "reporting_lag_days": 30,
    "exclude_cancelled": True,
    "exclude_direct_deals": True,
    "mad_outlier_threshold": 3.5,
    "min_deals_for_stat": 5,
}


class TestStore(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp(), "m.db")
        self.s = Store(self.db)

    def test_series_roundtrip_and_upsert(self):
        self.s.put_series([Observation("x", "k", dt.date(2026, 1, 1), 0.03)])
        self.s.put_series([Observation("x", "k", dt.date(2026, 1, 1), 0.04)])
        self.assertEqual(self.s.latest("x", "k"), (dt.date(2026, 1, 1), 0.04))
        self.assertEqual(len(self.s.series("x", "k")), 1)

    def test_latest_returns_none_when_empty(self):
        self.assertIsNone(self.s.latest("nope", "nope"))

    def test_dirty_deals_excluded_by_default(self):
        self.s.put_deals([
            Deal("t", "111", "trade", dt.date(2026, 1, 1), "A", 84.0, 3, 5e8),
            Deal("t", "111", "trade", dt.date(2026, 1, 2), "B", 84.0, 3, 9e8,
                 cancelled=True),
            Deal("t", "111", "trade", dt.date(2026, 1, 3), "C", 84.0, 3, 1e8,
                 direct_deal=True),
        ])
        self.assertEqual(len(self.s.deals("111", "trade")), 1)
        self.assertEqual(len(self.s.deals("111", "trade", include_dirty=True)), 3)

    def test_collection_log(self):
        self.s.log("c", "ok", 5, "msg")
        runs = self.s.last_runs()
        self.assertEqual(runs[0]["collector"], "c")
        self.assertEqual(runs[0]["rows"], 5)


class TestCleaning(unittest.TestCase):
    def setUp(self):
        self.s = Store(Path(tempfile.mkdtemp(), "m.db"))
        self.today = dt.date(2026, 9, 5)

    def _add(self, deals):
        self.s.put_deals(deals)

    def test_reporting_lag_window_excluded(self):
        """최근 신고 지연 구간을 그대로 쓰면 시세가 항상 왜곡된다."""
        old = [Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                    f"A{i}", 84.0, i, 7e8 + i) for i in range(10)]
        recent = [Deal("t", "1", "trade", self.today - dt.timedelta(days=3),
                       f"R{i}", 84.0, i, 1e9) for i in range(10)]
        self._add(old + recent)
        st = clean_price_stat(self.s, "1", "trade", CLEANING, as_of=self.today)
        self.assertEqual(st.n_used, 10)
        self.assertLess(st.median, 8e8)
        self.assertTrue(any("신고지연" in n for n in st.notes))

    def test_outliers_removed(self):
        base = [Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                     f"A{i}", 84.0, i, 7e8) for i in range(20)]
        base.append(Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                         "OUT", 84.0, 99, 5e9))
        self._add(base)
        st = clean_price_stat(self.s, "1", "trade", CLEANING, as_of=self.today)
        self.assertEqual(st.n_used, 20)
        self.assertTrue(any("이상치" in n for n in st.notes))

    def test_area_filter(self):
        self._add([
            Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                 "small", 59.0, 3, 4e8),
            Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                 "big", 84.0, 3, 7e8),
        ])
        st = clean_price_stat(self.s, "1", "trade", CLEANING,
                              area_min=80, area_max=90, as_of=self.today)
        self.assertEqual(st.n_used, 1)
        self.assertAlmostEqual(st.median, 7e8)

    def test_small_sample_marked_unreliable(self):
        """표본이 적으면 통계인 척하면 안 된다."""
        self._add([Deal("t", "1", "trade", self.today - dt.timedelta(days=60),
                        f"A{i}", 84.0, i, 7e8) for i in range(3)])
        st = clean_price_stat(self.s, "1", "trade", CLEANING, as_of=self.today)
        self.assertFalse(st.reliable)
        self.assertTrue(any("신뢰하지" in n for n in st.notes))

    def test_no_data_returns_nan_not_zero(self):
        st = clean_price_stat(self.s, "999", "trade", CLEANING, as_of=self.today)
        self.assertNotEqual(st.median, st.median)     # NaN
        self.assertFalse(st.reliable)


class TestCollectorContracts(unittest.TestCase):
    def test_missing_api_key_skips_not_crashes(self):
        """키가 없다고 시스템 전체가 멈추면 안 된다."""
        import os

        for var in ("ECOS_API_KEY", "DATA_GO_KR_KEY"):
            os.environ.pop(var, None)
        store = Store(Path(tempfile.mkdtemp(), "m.db"))
        r = MolitCollector().collect(store, {"molit": {}})
        self.assertEqual(r.status, "skipped")
        self.assertIn("DATA_GO_KR_KEY", r.message)

    def test_molit_parses_xml_and_flags_dirty_rows(self):
        xml = """<response><body><items>
          <item><dealYear>2026</dealYear><dealMonth>3</dealMonth><dealDay>15</dealDay>
                <aptNm>테스트</aptNm><excluUseAr>84.97</excluUseAr><floor>7</floor>
                <buildYear>2015</buildYear><dealAmount>85,000</dealAmount></item>
          <item><dealYear>2026</dealYear><dealMonth>3</dealMonth><dealDay>20</dealDay>
                <aptNm>취소건</aptNm><excluUseAr>84.97</excluUseAr><floor>3</floor>
                <dealAmount>99,000</dealAmount><cdealType>O</cdealType></item>
          <item><dealYear>2026</dealYear><dealMonth>3</dealMonth><dealDay>21</dealDay>
                <aptNm>직거래</aptNm><excluUseAr>84.97</excluUseAr><floor>4</floor>
                <dealAmount>50,000</dealAmount><dealingGbn>직거래</dealingGbn></item>
        </items></body></response>"""
        deals = MolitCollector()._parse(xml, "41135", "trade")
        self.assertEqual(len(deals), 3)
        self.assertAlmostEqual(deals[0].price, 850_000_000)
        self.assertTrue(deals[1].cancelled)
        self.assertTrue(deals[2].direct_deal)

    def test_molit_rent_splits_jeonse_and_wolse(self):
        xml = """<response><body><items>
          <item><dealYear>2026</dealYear><dealMonth>3</dealMonth><dealDay>1</dealDay>
                <aptNm>전세건</aptNm><excluUseAr>84.9</excluUseAr><floor>3</floor>
                <deposit>50,000</deposit><monthlyRent>0</monthlyRent></item>
          <item><dealYear>2026</dealYear><dealMonth>3</dealMonth><dealDay>2</dealDay>
                <aptNm>월세건</aptNm><excluUseAr>84.9</excluUseAr><floor>4</floor>
                <deposit>10,000</deposit><monthlyRent>120</monthlyRent></item>
        </items></body></response>"""
        deals = MolitCollector()._parse(xml, "41135", "rent")
        kinds = {d.complex_name: d.deal_kind for d in deals}
        self.assertEqual(kinds["전세건"], "jeonse")
        self.assertEqual(kinds["월세건"], "wolse")
        self.assertAlmostEqual(deals[1].monthly_rent, 1_200_000)

    def test_molit_skips_malformed_rows(self):
        xml = "<response><body><items><item><aptNm>깨진행</aptNm></item></items></body></response>"
        self.assertEqual(MolitCollector()._parse(xml, "1", "trade"), [])

    def test_manual_supply_requires_source_comment(self):
        """출처 없는 숫자는 3개월 뒤 쓸 수 없다."""
        d = Path(tempfile.mkdtemp())
        csv = d / "supply.csv"
        csv.write_text("region_code,year_month,units\n41135,202601,1200\n",
                       encoding="utf-8")
        store = Store(d / "m.db")
        r = ManualSupplyCollector().collect(
            store, {"manual": {"supply_csv": str(csv)}})
        self.assertEqual(r.status, "ok")
        self.assertTrue(any("출처" in w for w in r.warnings))

    def test_manual_supply_accepts_sourced_file(self):
        d = Path(tempfile.mkdtemp())
        csv = d / "supply.csv"
        csv.write_text("# 출처: 예시 집계, 조회일 2026-09-05\n"
                       "region_code,year_month,units\n41135,202601,1200\n",
                       encoding="utf-8")
        store = Store(d / "m.db")
        r = ManualSupplyCollector().collect(
            store, {"manual": {"supply_csv": str(csv)}})
        self.assertEqual(r.rows, 1)
        self.assertEqual(r.warnings, [])

    def test_template_has_source_placeholder(self):
        p = init_supply_template(Path(tempfile.mkdtemp()) / "s.csv")
        self.assertIn("출처", p.read_text(encoding="utf-8"))

    def test_base_collector_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            Collector().collect(None, {})


if __name__ == "__main__":
    unittest.main()
