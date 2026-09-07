# -*- coding: utf-8 -*-
"""백테스트 엔진 — 신호 -> 비중 -> 비용차감 수익 -> 진단."""
from __future__ import annotations
import pandas as pd
import signals, portfolio, costs, diagnostics


def run(close: pd.DataFrame, cfg) -> dict:
    close = close.dropna(how="all")
    # 유니버스: 최소 이력 요건
    valid = close.notna().cumsum() >= cfg.min_history_w
    close = close.where(valid)

    score = signals.resistance_failure_score(close, cfg)
    asset_ret = close.pct_change(fill_method=None)
    fwd = signals.forward_return(close, cfg.holding_weeks)

    w = portfolio.build(score, asset_ret, cfg)
    gross = (w.shift(1) * asset_ret).sum(axis=1)
    net, cost_series = costs.apply_costs(gross, w, cfg)

    if cfg.oos_start:
        cut = pd.Timestamp(cfg.oos_start)
        net_eval, score_eval, fwd_eval = net[net.index >= cut], score[score.index >= cut], fwd[fwd.index >= cut]
    else:
        net_eval, score_eval, fwd_eval = net, score, fwd

    ppy = 52.0 / cfg.rebalance_every_w
    ic = diagnostics.information_coefficient(score_eval, fwd_eval)
    qs = diagnostics.quantile_monotonicity(score_eval, fwd_eval)
    stats = diagnostics.perf_stats(net_eval, ppy)
    return dict(score=score, weights=w, gross=gross, net=net, cost=cost_series,
                ic=ic, quantiles=qs, stats=stats,
                turnover=costs.turnover(w).mean(),
                checks=diagnostics.falsification_report(stats, ic, qs, cfg))


def report(res: dict, cfg, title: str = "") -> str:
    s, out = res["stats"], []
    out.append("=" * 74)
    out.append(f"백테스트 {title}".strip())
    out.append(cfg.describe())
    out.append("=" * 74)
    if not s:
        out.append("표본 부족 — 평가 불가"); return "\n".join(out)
    out.append(f"  기간 {s['years']:.1f}년 ({s['n_periods']}주)   "
               f"평균 회전율 {res['turnover']:.1%}/주")
    out.append(f"  연수익 {s['ann_return']:+.2%}   연변동성 {s['ann_vol']:.2%} "
               f"(목표 {cfg.target_vol:.0%}{' — 레버리지 금지 상한에 걸려 미달' if s['ann_vol'] < cfg.target_vol*0.8 else ''})"
               f"   샤프 {s['sharpe']:+.2f}")
    out.append(f"  최대낙폭 {s['max_drawdown']:.2%}   주간수익 t={s['t_stat']:+.2f}")
    out.append(f"  비용 차감액 연 {res['cost'].mean()*52:.2%}")
    out.append(f"  IC 평균 {res['ic'].mean():+.4f} (관측 {len(res['ic'])}주)")
    out.append("  분위별 전방수익: " + "  ".join(f"{k} {v:+.3%}" for k, v in res["quantiles"].items()))
    out.append("")
    out.append("  반증 조건 판정 (12.7):")
    for name, ok, detail in res["checks"]:
        out.append(f"    [{'통과' if ok else '미달'}] {name:<22} {detail}")
    n_fail = sum(1 for _, ok, _ in res["checks"] if not ok)
    out.append("")
    out.append(f"  => {'운용 후보' if n_fail == 0 else f'{n_fail}개 조건 미달 — 폐기 또는 보류'}")
    return "\n".join(out)
