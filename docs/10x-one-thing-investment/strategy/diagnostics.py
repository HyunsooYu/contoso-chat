# -*- coding: utf-8 -*-
"""진단 — IC, 분위 단조성, 탐색량 보정 허들, 반증 조건 판정(12.5~12.7)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def information_coefficient(score: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """주간 횡단면 스피어만 순위상관. 가설이 맞으면 음(-)이어야 한다."""
    out = {}
    for t in score.index:
        s, f = score.loc[t], fwd.loc[t] if t in fwd.index else None
        if f is None:
            continue
        pair = pd.concat([s, f], axis=1).dropna()
        if len(pair) >= 10:
            # 스피어만 = 순위로 바꾼 뒤의 피어슨 (scipy 의존 제거)
            a = pair.iloc[:, 0].rank()
            b = pair.iloc[:, 1].rank()
            out[t] = a.corr(b)
    return pd.Series(out).sort_index()


def quantile_monotonicity(score: pd.DataFrame, fwd: pd.DataFrame, n_q: int = 5) -> pd.Series:
    """분위별 평균 전방수익. 진짜 신호는 분위 간 단조 기울기를 보인다."""
    acc = {q: [] for q in range(n_q)}
    for t in score.index:
        if t not in fwd.index:
            continue
        pair = pd.concat([score.loc[t], fwd.loc[t]], axis=1).dropna()
        if len(pair) < n_q * 3:
            continue
        pair.columns = ["s", "f"]
        labels = pd.qcut(pair["s"].rank(method="first"), n_q, labels=False)
        for q in range(n_q):
            acc[q].append(pair.loc[labels == q, "f"].mean())
    return pd.Series({f"Q{q+1}": np.nanmean(v) if v else np.nan for q, v in acc.items()})


def is_monotonic(qs: pd.Series) -> bool:
    v = qs.dropna().values
    return len(v) >= 3 and (all(np.diff(v) <= 0) or all(np.diff(v) >= 0))


def newey_west_t(x: pd.Series, lags: int) -> float:
    """중첩(overlapping) 관측을 보정한 t값.

    보유기간 h 주의 전방수익으로 IC 를 매주 계산하면 연속한 h개 관측이 같은 구간을
    공유한다. 단순 t는 이 중복을 독립 표본으로 세어 t를 부풀리고, 귀무 데이터에서도
    |t|>2 가 자주 나온다(측정: 20회 중 15~20%, 명목 5% 대비). Newey-West 로
    자기상관을 보정하면 이 오탐이 명목 수준으로 내려간다.
    """
    v = x.dropna().to_numpy(dtype=float)
    n = len(v)
    if n < 8:
        return 0.0
    e = v - v.mean()
    g0 = float(e @ e) / n
    s = g0
    for k in range(1, min(lags, n - 1) + 1):
        gk = float(e[k:] @ e[:-k]) / n
        s += 2.0 * (1.0 - k / (lags + 1.0)) * gk     # Bartlett 커널
    s = max(s, 1e-18)
    return float(v.mean() / np.sqrt(s / n))


def deflated_hurdle(n_hypotheses: int, years: float) -> float:
    """탐색량 N을 감안했을 때 '운으로도 나오는' 샤프 (9부 검증 S)."""
    if n_hypotheses <= 1 or years <= 0:
        return 0.0
    return float(np.sqrt(2 * np.log(n_hypotheses)) / np.sqrt(years))


def perf_stats(net_ret: pd.Series, periods_per_year: float) -> dict:
    r = net_ret.dropna()
    if len(r) < 8:
        return {}
    eq = (1 + r).cumprod()
    ann_ret = eq.iloc[-1] ** (periods_per_year / len(r)) - 1
    ann_vol = r.std() * np.sqrt(periods_per_year)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    t_stat = r.mean() / (r.std() / np.sqrt(len(r))) if r.std() > 0 else 0.0
    return dict(years=len(r) / periods_per_year, ann_return=ann_ret, ann_vol=ann_vol,
                sharpe=sharpe, max_drawdown=dd, t_stat=t_stat, n_periods=len(r))


def falsification_report(stats: dict, ic: pd.Series, qs: pd.Series, cfg) -> list[tuple[str, bool, str]]:
    """12.7의 반증 조건을 그대로 판정한다. False = 폐기 신호."""
    checks = []
    ic_t = newey_west_t(ic, max(cfg.holding_weeks - 1, 1))
    checks.append(("IC가 0과 유의하게 다름", abs(ic_t) >= cfg.kill_ic_t,
                   f"IC 평균 {ic.mean():+.4f}, NW t={ic_t:+.2f} (기준 |t|>={cfg.kill_ic_t})"))
    net_t = stats.get("t_stat", 0.0)
    checks.append(("비용차감 후 수익 t값", net_t >= cfg.kill_net_t,
                   f"NW t={net_t:+.2f} (기준 >={cfg.kill_net_t})"))
    checks.append(("분위 단조성", is_monotonic(qs),
                   " ".join(f"{k}={v:+.3%}" for k, v in qs.items())))
    checks.append(("최대낙폭 한도", abs(stats.get("max_drawdown", -1)) <= cfg.kill_max_dd,
                   f"MDD {stats.get('max_drawdown', float('nan')):.1%} "
                   f"(한도 {cfg.kill_max_dd:.0%})"))
    hurdle = deflated_hurdle(cfg.n_hypotheses, stats.get("years", 0))
    checks.append(("탐색량 보정 허들 통과", stats.get("sharpe", 0) >= hurdle,
                   f"샤프 {stats.get('sharpe', 0):.2f} vs 허들 {hurdle:.2f} "
                   f"(N={cfg.n_hypotheses})"))
    return checks
