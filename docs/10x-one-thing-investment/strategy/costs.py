# -*- coding: utf-8 -*-
"""거래비용 모델. 낙관적 가정이 백테스트를 죽이는 가장 흔한 원인이므로 분리해 둔다."""
from __future__ import annotations
import pandas as pd


def turnover(weights: pd.DataFrame) -> pd.Series:
    """기간별 단측 회전율 = sum(|w_t - w_{t-1}|) / 2."""
    return weights.diff().abs().sum(axis=1).fillna(weights.abs().sum(axis=1)) / 2.0


def apply_costs(gross_ret: pd.Series, weights: pd.DataFrame, cfg) -> tuple[pd.Series, pd.Series]:
    """거래비용과 숏 대차비용을 차감한 순수익을 돌려준다."""
    to = turnover(weights)
    trade_cost = to * 2.0 * (cfg.cost_bps_per_side / 1e4)      # 왕복
    short_gross = weights.clip(upper=0).abs().sum(axis=1)
    periods_per_year = 52.0 / cfg.rebalance_every_w
    borrow = short_gross * (cfg.borrow_bps_annual / 1e4) / periods_per_year
    total = trade_cost + borrow
    return gross_ret - total, total
