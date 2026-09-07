# -*- coding: utf-8 -*-
"""
CLI.

  python3 run.py expect                 기대수익 산술 (백테스트 이전에 먼저 볼 것)
  python3 run.py selftest               귀무/엣지 합성 데이터로 파이프라인 자기검증
  python3 run.py backtest --csv px.csv  실데이터 백테스트
  python3 run.py audit --csv px.csv     생존편향 감사 (백테스트 전에 반드시)
  python3 run.py delist-sens            폐지수익 가정 민감도
"""
from __future__ import annotations
import argparse, sys
import pandas as pd
import data, backtest, expectations, universe
from config import DEFAULT, Config


def cmd_expect(_):
    print("=" * 74)
    print("기대수익 산술  IR = IC x sqrt(유효 BR),  순수익 = IR x 목표변동성 - 비용")
    print("=" * 74)
    print(expectations.table())
    print()
    print("읽는 법:")
    print("  · IC=0 이면 순수익은 비용만큼 음수다. 이것이 기본값이며 대부분의 가설이 여기 있다.")
    print("  · IC=0.02~0.03 이 현실적인 '성공' 구간이다. 그 위는 기대하지 않는 편이 낫다.")
    print("  · 엣지가 진짜여도 손실년 확률은 25~35%다. 3년 중 1년은 마이너스라고 보고 시작한다.")
    print("  · 't=2까지' 열이 곧 '이 전략이 진짜인지 알게 되기까지'의 시간이다.")


def cmd_selftest(_):
    print("파이프라인 자기검증: 엣지가 없을 때 '없다'고 말하는지부터 확인한다.\n")
    cfg = DEFAULT
    for label, ic in (("귀무 데이터 (진짜 엣지 = 0)", 0.0),
                      ("엣지 심은 데이터 (IC 0.06)", 0.06)):
        px, dl = data.synth_delisted(n_assets=cfg.top_n_by_liquidity, weeks=520,
                                     seed=7, embedded_ic=ic, hazard=0.03)
        res = backtest.run(px, cfg, delistings=dl)
        print(backtest.report(res, cfg, title=f"— {label}"))
        print()
    print("=" * 74)
    print("이 두 결과가 서로 다르게 나와야 파이프라인을 신뢰할 수 있다.")
    print("귀무 데이터에서 '운용 후보'가 나온다면 코드나 진단에 결함이 있는 것이다.")


def cmd_backtest(args):
    cfg = DEFAULT if not args.oos else Config(**{**DEFAULT.__dict__, "oos_start": args.oos})
    px = data.load_csv(args.csv)
    dl = universe.load_delistings(args.delistings) if args.delistings else None
    print(f"로드: {px.shape[1]}개 심볼 x {px.shape[0]}주 "
          f"({px.index[0].date()} ~ {px.index[-1].date()})"
          + (f", 폐지 {len(dl)}건" if dl is not None else ", 폐지목록 없음"))
    res = backtest.run(px, cfg, delistings=dl)
    print(backtest.report(res, cfg, title=f"— {args.csv}"))


def cmd_audit(args):
    px = data.load_csv(args.csv)
    dl = universe.load_delistings(args.delistings) if args.delistings else None
    print(universe.audit_report(universe.audit(px, dl)))


def cmd_delist_sens(args):
    """폐지수익 가정을 바꿔가며 성과가 얼마나 움직이는지 측정한다.

    이 전략은 약세 종목을 숏하므로 폐지수익을 더 음수로 놓을수록 성과가 좋아진다.
    따라서 '가장 불리한 가정'(0%)에서도 살아남는지가 판정 기준이다.
    """
    cfg = DEFAULT
    px, dl = data.synth_delisted(n_assets=cfg.top_n_by_liquidity, weeks=520,
                                 seed=7, embedded_ic=0.06, hazard=0.03)
    print("=" * 74)
    print(f"폐지수익 가정 민감도  (합성 엣지 데이터 IC 0.06, 폐지 {len(dl)}건)")
    print("=" * 74)
    print(f"{'가정':<34}{'연수익':>10}{'샤프':>8}{'MDD':>9}")
    rows = [("주입 없음 (조용히 소멸 — 흔한 오류)", None, None),
            ("0%   합병·현금청산 근사 (가장 불리)", 0.0, None),
            ("-30% Shumway 1997 NYSE/AMEX", -0.30, None),
            ("-55% Shumway-Warther 1999 Nasdaq", -0.55, None),
            ("-100% 전액 손실", -1.00, None),
            ("사유별 가정 (기본 설정)", "reason", None)]
    for label, ov, _ in rows:
        if ov is None:
            res = backtest.run(px, Config(**{**cfg.__dict__,
                                             "require_delisting_data": False}))
        elif ov == "reason":
            res = backtest.run(px, cfg, delistings=dl)
        else:
            res = backtest.run(px, Config(**{**cfg.__dict__, "delist_override": ov}),
                               delistings=dl)
        s = res["stats"]
        print(f"{label:<34}{s['ann_return']:>+9.2%}{s['sharpe']:>+8.2f}"
              f"{s['max_drawdown']:>9.2%}")
    print()
    print("읽는 법: 위아래 폭이 곧 '데이터 가정만으로 만들어지는 성과'다.")
    print("        폭이 결론을 뒤집을 만큼 크면, 그 결론은 전략이 아니라 가정의 산물이다.")


def main():
    ap = argparse.ArgumentParser(description="저항실패 점수 전략 (12부 명세)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("expect").set_defaults(f=cmd_expect)
    sub.add_parser("selftest").set_defaults(f=cmd_selftest)
    b = sub.add_parser("backtest"); b.add_argument("--csv", required=True)
    b.add_argument("--delistings", default=None, help="symbol,delist_date,reason CSV")
    b.add_argument("--oos", default=None, help="표본외 시작일 YYYY-MM-DD")
    b.set_defaults(f=cmd_backtest)
    au = sub.add_parser("audit"); au.add_argument("--csv", required=True)
    au.add_argument("--delistings", default=None)
    au.set_defaults(f=cmd_audit)
    sub.add_parser("delist-sens").set_defaults(f=cmd_delist_sens)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    sys.exit(main())
