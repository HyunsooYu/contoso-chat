# -*- coding: utf-8 -*-
"""
선등록(pre-registration) 명세와 잠금.

이 파일이 곧 '가설 등록 문서'다. 값을 바꾸면 해시가 바뀌고, 그 사실이 기록된다.
바꾸는 것 자체는 반칙이 아니다 — 바꾼 사실을 세지 않는 것이 반칙이다(12.6).
n_hypotheses 를 올리면 diagnostics 가 요구 허들을 자동으로 높인다.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
import hashlib, json


@dataclass(frozen=True)
class Config:
    # ---- 가설 H1 (12.5) -------------------------------------------------
    # "자산이 최근 고점 돌파에 반복 실패할수록 이후 횡단면 초과수익이 낮다."
    lookback_high_w: int = 52       # A: 최고가 기준 기간(주)
    approach_window_w: int = 26     # B: 재시도 실패를 세는 기간(주)
    approach_tol: float = 0.03      # B: 최고가의 3% 이내 접근 = '시도'
    breakout_window_w: int = 4      # B: 시도 후 이 기간 내 돌파 못하면 '실패'
    w_a: float = 0.4                # A 가중치 (고점 대비 위치)
    w_b: float = 0.4                # B 가중치 (재시도 실패 누적)
    w_c: float = 0.2                # C 가중치 (최근성)

    # ---- 유니버스 -------------------------------------------------------
    min_history_w: int = 156        # 최소 3년 이력
    top_n_by_liquidity: int = 50    # 거래대금 상위 N개만
    # 주의: 상장폐지 종목을 반드시 포함한 데이터를 써야 한다(생존편향).

    # ---- 포트폴리오 (12.3, 12.4) ---------------------------------------
    quantile: float = 0.20          # 상위/하위 20%
    neutral: bool = True            # 횡단면 금액 중립(롱숏)
    target_vol: float = 0.20        # 목표 연 변동성
    vol_lookback_w: int = 26        # 실현변동성 추정 기간
    max_gross: float = 1.0          # 총 익스포저 상한 = 레버리지 금지
    max_weight_per_asset: float = 0.10
    rebalance_every_w: int = 1
    turnover_deadband: float = 0.25 # 목표비중 변화가 이보다 작으면 거래 생략

    # ---- 생존편향 (13.7) ------------------------------------------------
    require_delisting_data: bool = True   # 소멸 종목이 없는 패널은 백테스트 거부
    delist_override: float | None = None  # 폐지수익을 한 값으로 덮음(민감도 분석용)

    # ---- 비용 -----------------------------------------------------------
    cost_bps_per_side: float = 15.0 # 수수료+세금+스프레드+슬리피지 (실측치로 교체)
    borrow_bps_annual: float = 200.0  # 숏 대차/펀딩 비용

    # ---- 평가 -----------------------------------------------------------
    holding_weeks: int = 4          # IC 계산용 전방 수익 기간
    n_hypotheses: int = 1           # 지금까지 시험한 명세의 개수 (탐색량 N)
    oos_start: str | None = None    # 표본외 시작일 'YYYY-MM-DD'

    # ---- 반증 조건 (12.7) -----------------------------------------------
    kill_ic_t: float = 2.0          # 2년 롤링 IC t값이 이보다 낮으면 폐기 검토
    kill_net_t: float = 1.0         # 비용차감 후 롱숏 t값 하한
    kill_max_dd: float = 0.25       # 최대낙폭 한도 -> 초과 시 운용 중단

    notes: str = "H1: resistance-failure score, cross-sectionally neutral"

    def fingerprint(self) -> str:
        d = {k: v for k, v in asdict(self).items()
             if k not in ("notes", "oos_start", "delist_override")}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def describe(self) -> str:
        return (f"config fingerprint = {self.fingerprint()}  "
                f"(n_hypotheses={self.n_hypotheses})")


DEFAULT = Config()
