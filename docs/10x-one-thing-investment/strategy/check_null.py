# -*- coding: utf-8 -*-
"""
귀무 오탐율 측정 — 엣지가 0인 합성 데이터를 반복 생성해
반증 조건이 '가짜 합격'을 얼마나 내는지 센다.

  python3 check_null.py --reps 100

명목 유의수준이 5%면 |t|>2 는 100회 중 5회 근처여야 한다.
그보다 훨씬 높으면 t값 자체가 부풀려진 것이고, 그 파이프라인은
귀무 데이터를 운용 후보로 승격시킨다.
"""
from __future__ import annotations
import argparse
import numpy as np
import data, backtest, diagnostics
from config import DEFAULT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=100)
    ap.add_argument("--hazard", type=float, default=0.03)
    a = ap.parse_args()
    cfg = DEFAULT
    nw, naive = [], []
    for seed in range(1, a.reps + 1):
        px, dl = data.synth_delisted(cfg.top_n_by_liquidity, 520, seed,
                                     embedded_ic=0.0, hazard=a.hazard)
        ic = backtest.run(px, cfg, delistings=dl)["ic"].dropna()
        nw.append(diagnostics.newey_west_t(ic, max(cfg.holding_weeks - 1, 1)))
        naive.append(ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic))))
    nw, naive = np.abs(np.array(nw)), np.abs(np.array(naive))
    n = a.reps
    se = lambda p: (p * (1 - p) / n) ** 0.5
    print("=" * 74)
    print(f"귀무 오탐율 ({n}회, 진짜 엣지 = 0)")
    print("=" * 74)
    for lbl, t in (("단순 t (중첩 무시)", naive), ("Newey-West t (적용중)", nw)):
        p = float((t > 2).mean())
        print(f"  {lbl:<22} |t|>2 비율 {p:>5.0%} (±{se(p):.1%})   평균 |t| {t.mean():.2f}")
    print()
    print("  명목 5%와 비교해 초과하면, 그 t값으로는 가설을 기각할 수 없다.")


if __name__ == "__main__":
    main()
