# -*- coding: utf-8 -*-
"""
'실제로 얼마를 기대할 수 있는가'의 산술.

Grinold 기본법칙:  IR = IC x sqrt(BR_eff)
연 초과수익 = IR x 목표변동성 - 비용
이 계산은 백테스트 이전에, 종이 위에서 먼저 해야 한다.
"""
from __future__ import annotations
import math


def expected(ic: float, n_assets: int, rebal_per_year: float,
             var_inflation: float, target_vol: float,
             turnover_per_rebal: float, cost_bps_side: float,
             borrow_bps: float = 0.0, short_gross: float = 0.5) -> dict:
    br_nominal = n_assets * rebal_per_year
    br_eff = br_nominal / max(var_inflation, 1e-9)
    ir = ic * math.sqrt(br_eff)
    gross = ir * target_vol
    cost = turnover_per_rebal * 2 * (cost_bps_side / 1e4) * rebal_per_year
    borrow = short_gross * (borrow_bps / 1e4)
    net = gross - cost - borrow
    net_ir = net / target_vol if target_vol > 0 else 0.0
    p_loss_year = 0.5 * (1 + math.erf(-net_ir / math.sqrt(2))) if target_vol > 0 else 0.5
    years_to_t2 = (2 / net_ir) ** 2 if net_ir > 0 else float("inf")
    return dict(br_nominal=br_nominal, br_eff=br_eff, ir_gross=ir,
                ret_gross=gross, cost=cost, borrow=borrow, ret_net=net,
                ir_net=net_ir, p_losing_year=p_loss_year, years_to_t2=years_to_t2)


def table(n_assets=50, rebal=52, var_inflation=2.1, target_vol=0.20,
          turnover=0.35, cost_bps=15.0, borrow_bps=200.0) -> str:
    lines = []
    lines.append(f"가정: 자산 {n_assets}개, 연 {rebal}회 리밸런싱, 분산팽창 {var_inflation}배,")
    lines.append(f"      목표변동성 {target_vol:.0%}, 회차당 회전율 {turnover:.0%},")
    lines.append(f"      편측비용 {cost_bps:.0f}bp, 숏 대차 {borrow_bps:.0f}bp/년")
    lines.append("")
    hdr = (f"{'IC':>6} {'유효BR':>9} {'총 IR':>7} {'총수익':>8} {'비용':>8} "
           f"{'순수익':>8} {'순 IR':>7} {'손실년 확률':>11} {'t=2까지':>9}")
    lines.append(hdr); lines.append("-" * len(hdr))
    for ic in (0.00, 0.01, 0.02, 0.03, 0.05):
        e = expected(ic, n_assets, rebal, var_inflation, target_vol,
                     turnover, cost_bps, borrow_bps)
        yrs = "-" if e["years_to_t2"] == float("inf") else f"{e['years_to_t2']:.1f}년"
        lines.append(f"{ic:>6.2f} {e['br_eff']:>9.0f} {e['ir_gross']:>7.2f} "
                     f"{e['ret_gross']:>7.1%} {e['cost']+e['borrow']:>7.1%} "
                     f"{e['ret_net']:>7.1%} {e['ir_net']:>7.2f} "
                     f"{e['p_losing_year']:>10.0%} {yrs:>9}")
    return "\n".join(lines)
