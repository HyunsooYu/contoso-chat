"""데이터 수집기.

수집하지 않는 것:
  - 포털 호가 크롤링: 약관 위반이고, 호가는 실거래가 아니라 노이즈다.

수집 빈도에 대해:
  리뷰 결론대로 **일 단위 수집은 가치가 거의 없다.** 전세 만기 전에는
  행동 공간이 거의 닫혀 있어서, 매일 수집해도 바뀌는 결정이 없다.
  월 1회 수동 실행으로 충분하고, 그러면 크롤러 유지보수 부담이 사라진다.
  `python -m fde collect` 를 월 1회 돌리는 것을 권장한다.
"""
from fde.collectors.base import CollectResult, Collector, load_collector_config
from fde.collectors.ecos import EcosCollector
from fde.collectors.manual import ManualSupplyCollector, init_supply_template
from fde.collectors.molit import MolitCollector, clean_price_stat
from fde.collectors.store import Deal, Observation, Store

ALL_COLLECTORS = [EcosCollector(), MolitCollector(), ManualSupplyCollector()]

__all__ = [
    "ALL_COLLECTORS", "CollectResult", "Collector", "Deal", "EcosCollector",
    "ManualSupplyCollector", "MolitCollector", "Observation", "Store",
    "clean_price_stat", "init_supply_template", "load_collector_config",
]
