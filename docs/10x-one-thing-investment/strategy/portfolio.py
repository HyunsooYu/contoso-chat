# -*- coding: utf-8 -*-
"""횡단면 중립 포지션 구성(12.3) + 변동성 타게팅(12.4) + 회전율 제어."""
from __future__ import annotations
import numpy as np
import pandas as pd


def raw_weights(score: pd.DataFrame, cfg) -> pd.DataFrame:
    """점수 상위 q = 매도, 하위 q = 매수. 각 다리 동일비중, 금액 중립."""
    w = pd.DataFrame(0.0, index=score.index, columns=score.columns)
    for t, row in score.iterrows():
        s = row.dropna()
        k = int(len(s) * cfg.quantile)
        if k < 2:
            continue
        order = s.sort_values()
        longs, shorts = order.index[:k], order.index[-k:]
        w.loc[t, longs] = 1.0 / (2 * k) if cfg.neutral else 0.0
        w.loc[t, shorts] = -1.0 / (2 * k)
        if not cfg.neutral:                      # 숏 전용 모드(비교용)
            w.loc[t, shorts] = -1.0 / k
    return w.clip(-cfg.max_weight_per_asset, cfg.max_weight_per_asset)


def vol_scaled(w: pd.DataFrame, asset_ret: pd.DataFrame, cfg) -> pd.DataFrame:
    """전 기간 실현변동성(시차 적용)으로 목표변동성에 맞춘다. 상한 max_gross."""
    gross_ret = (w.shift(1) * asset_ret).sum(axis=1)
    periods = 52.0 / cfg.rebalance_every_w
    realized = gross_ret.rolling(cfg.vol_lookback_w, min_periods=8).std() * np.sqrt(periods)
    scale = (cfg.target_vol / realized.replace(0.0, np.nan)).shift(1)
    scale = scale.clip(upper=cfg.max_gross).fillna(0.0)   # 추정 전에는 미투자
    return w.mul(scale, axis=0)


def apply_deadband(w: pd.DataFrame, cfg) -> pd.DataFrame:
    """목표비중 변화가 작으면 거래하지 않는다 — 회전율(=비용)을 직접 줄인다."""
    out = w.copy()
    prev = None
    for t in w.index:
        cur = w.loc[t]
        if prev is None:
            prev = cur
            out.loc[t] = cur
            continue
        denom = prev.abs().sum()
        change = (cur - prev).abs().sum() / (denom if denom > 0 else 1.0)
        if change < cfg.turnover_deadband:
            out.loc[t] = prev            # 유지
        else:
            prev = cur
    return out


def build(score: pd.DataFrame, asset_ret: pd.DataFrame, cfg) -> pd.DataFrame:
    w = raw_weights(score, cfg)
    w = vol_scaled(w, asset_ret, cfg)
    return apply_deadband(w, cfg)
