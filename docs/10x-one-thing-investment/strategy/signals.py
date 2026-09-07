# -*- coding: utf-8 -*-
"""
저항실패 점수 (12.2).

가설의 '내용'을 그대로 코드로 옮긴다:
  A = 최근 고점 대비 얼마나 아래에 있는가
  B = 최근 고점 근처까지 갔다가 돌파에 실패한 횟수
  C = 마지막 시도가 얼마나 최근인가
점수가 높을수록 '돌파 실패가 누적된 상태' -> 가설상 이후 수익이 낮다.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _zscore_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def resistance_failure_score(close: pd.DataFrame, cfg) -> pd.DataFrame:
    """close: index=주봉 날짜, columns=심볼. 반환: 같은 shape의 횡단면 z-score."""
    roll_high = close.rolling(cfg.lookback_high_w, min_periods=cfg.lookback_high_w // 2).max()

    # A: 고점 대비 위치 (0=고점, 클수록 아래)
    a = 1.0 - close / roll_high

    # B: '시도'(고점 3% 이내 접근) 후 breakout_window 내 신고가 실패 횟수
    near = close >= roll_high * (1.0 - cfg.approach_tol)
    w = cfg.breakout_window_w
    fwd_max = close.shift(-w).rolling(w, min_periods=1).max()   # t 시점의 t+1..t+w 최대값
    failed = (near & (fwd_max <= roll_high)).astype(float)
    # 미래 참조를 제거: 실패 판정은 breakout_window 만큼 지난 뒤에야 알 수 있다
    failed = failed.shift(w)
    b = failed.rolling(cfg.approach_window_w, min_periods=4).sum()

    # C: 마지막 접근 이후 경과 주수 (최근일수록 점수 높게)
    idx = pd.Series(np.arange(len(close)), index=close.index)
    last_near = near.mul(idx, axis=0).where(near).ffill()
    weeks_since = last_near.rsub(idx, axis=0)
    c = -(weeks_since / cfg.approach_window_w).clip(upper=2.0)

    za, zb, zc = (_zscore_cross_section(x) for x in (a, b, c))
    score = cfg.w_a * za + cfg.w_b * zb + cfg.w_c * zc
    return _zscore_cross_section(score)


def forward_return(close: pd.DataFrame, weeks: int) -> pd.DataFrame:
    return close.shift(-weeks) / close - 1.0
