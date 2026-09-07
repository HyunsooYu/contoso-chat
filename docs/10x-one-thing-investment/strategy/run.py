# -*- coding: utf-8 -*-
"""
CLI.

  python3 run.py expect                 기대수익 산술 (백테스트 이전에 먼저 볼 것)
  python3 run.py selftest               귀무/엣지 합성 데이터로 파이프라인 자기검증
  python3 run.py backtest --csv px.csv  실데이터 백테스트
"""
from __future__ import annotations
import argparse, sys
import data, backtest, expectations
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
        px = data.synth(n_assets=cfg.top_n_by_liquidity, weeks=520,
                        seed=7, embedded_ic=ic)
        res = backtest.run(px, cfg)
        print(backtest.report(res, cfg, title=f"— {label}"))
        print()
    print("=" * 74)
    print("이 두 결과가 서로 다르게 나와야 파이프라인을 신뢰할 수 있다.")
    print("귀무 데이터에서 '운용 후보'가 나온다면 코드나 진단에 결함이 있는 것이다.")


def cmd_backtest(args):
    cfg = DEFAULT if not args.oos else Config(**{**DEFAULT.__dict__, "oos_start": args.oos})
    px = data.load_csv(args.csv)
    print(f"로드: {px.shape[1]}개 심볼 x {px.shape[0]}주 "
          f"({px.index[0].date()} ~ {px.index[-1].date()})")
    res = backtest.run(px, cfg)
    print(backtest.report(res, cfg, title=f"— {args.csv}"))


def main():
    ap = argparse.ArgumentParser(description="저항실패 점수 전략 (12부 명세)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("expect").set_defaults(f=cmd_expect)
    sub.add_parser("selftest").set_defaults(f=cmd_selftest)
    b = sub.add_parser("backtest"); b.add_argument("--csv", required=True)
    b.add_argument("--oos", default=None, help="표본외 시작일 YYYY-MM-DD")
    b.set_defaults(f=cmd_backtest)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    sys.exit(main())
