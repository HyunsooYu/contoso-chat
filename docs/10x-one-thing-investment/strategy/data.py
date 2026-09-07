# -*- coding: utf-8 -*-
"""데이터 어댑터. 실데이터는 CSV로 받고, 파이프라인 점검용 합성 생성기를 함께 둔다."""
from __future__ import annotations
import numpy as np
import pandas as pd


def load_csv(path: str) -> pd.DataFrame:
    """CSV: date,symbol,close  -> 주봉 종가 wide 테이블.
    반드시 상장폐지 종목을 포함한 데이터를 쓸 것(생존편향은 모든 결과를 무효화한다)."""
    df = pd.read_csv(path, parse_dates=["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    return wide.resample("W-FRI").last()


def synth(n_assets=50, weeks=520, seed=7, embedded_ic=0.0,
          mkt_vol=0.35, idio_vol=0.45) -> pd.DataFrame:
    """합성 주봉. embedded_ic=0 이면 진짜 엣지가 없는 귀무 데이터.

    엣지를 심을 때는 '52주 고점 대비 이격'만을 구동변수로 쓴다. signals.py 의 점수는
    이격 외에 재시도 실패 횟수와 최근성을 함께 쓰므로 완전히 같은 식은 아니지만,
    부분적으로 겹친다 — 따라서 이 검사는 '파이프라인이 배선대로 도는가'의 점검이지
    신호의 유효성 증거가 아니다.
    """
    rng = np.random.default_rng(seed)
    mw, iw = mkt_vol / np.sqrt(52), idio_vol / np.sqrt(52)
    mkt = rng.normal(0.0, mw, weeks)
    idio = rng.normal(0.0, iw, (weeks, n_assets))
    logpx = np.zeros((weeks, n_assets))
    lvl = np.zeros(n_assets)
    HI = 52
    for t in range(weeks):
        drift = np.zeros(n_assets)
        if embedded_ic != 0.0 and t > HI:
            hi = logpx[max(0, t - HI):t].max(axis=0)
            gap = hi - lvl                      # 고점 대비 얼마나 아래인가(클수록 약세)
            z = (gap - gap.mean()) / (gap.std() + 1e-9)
            # 가설 방향: 고점 이탈이 클수록(=점수 높을수록) 이후 수익이 낮다
            drift = -embedded_ic * iw * np.sqrt(4) * z
        lvl = lvl + mkt[t] + idio[t] + drift
        logpx[t] = lvl
    px = 100 * np.exp(logpx)
    idx = pd.date_range("2016-01-01", periods=weeks, freq="W-FRI")
    return pd.DataFrame(px, index=idx,
                        columns=[f"A{i:03d}" for i in range(n_assets)])
