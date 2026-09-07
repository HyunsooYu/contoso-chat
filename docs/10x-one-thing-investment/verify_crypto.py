# -*- coding: utf-8 -*-
"""
후속 검증 V: "BTC/알트코인 주봉 삼산 -> 인버스, 삼곡(삼천) -> 레버리지"
표준 라이브러리만 사용. seed 고정.
"""
import math, random

SEED = 20260907
LINE = "=" * 78
def pct(x): return f"{x*100:.1f}%"
def norm_cdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))

# 삼산 검출기는 10부의 것을 그대로 재사용한다 (정의를 바꾸지 않는다 = 탐색량 N을 늘리지 않는다)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_sanzan import to_bars, pivots

# ----------------------------------------- AA. 크립토 변동성에서의 최적 배율
def part_AA():
    print(LINE); print("[AA] 크립토 변동성에서 켈리 최적 배율은 얼마인가")
    print("3부 검증 D의 공식을 그대로 적용: k* = 초과수익 / 분산")
    print("BTC 연 변동성은 최근 대략 40~70% 구간에서 움직였고, 알트는 그보다 높다.")
    print(f"\n{'변동성':>8} {'분산':>8} " + " ".join(f"{'mu='+pct(m):>12}" for m in (0.20, 0.30, 0.50)))
    for sig in (0.20, 0.40, 0.55, 0.70, 1.10):
        row = f"{pct(sig):>8} {sig**2:>8.3f} "
        for mu in (0.20, 0.30, 0.50):
            k = mu / sig ** 2
            row += f"{k:>11.2f}x"
        print(row)
    print("\n(참고: 주식 변동성 20%, 초과수익 6% -> k* = 1.85x — 3부에서 계산한 값)")
    print("\n해석: 변동성 55%에 초과수익 30%를 가정해도 k* = 0.99x다.")
    print("      즉 크립토는 '무레버리지 100% 보유'가 이미 켈리 최적선상에 있다.")
    print("      변동성 70%면 k* = 0.61x — 레버리지가 아니라 비중 축소가 최적이다.")
    print("      분모가 제곱이기 때문에, 변동성이 2.75배면 최적 배율은 7.6배 작아진다.")

# ------------------------------------------- BB. 레버리지/인버스의 기하 손실
def part_BB():
    print(); print(LINE); print("[BB] 레버리지와 인버스의 1년 후 자산배수 (변동성 손실 포함)")
    print("로그성장률 g(k) = k*mu - k^2*sigma^2/2. 표에는 자산배수 exp(g)를 적는다.")
    print("(g는 로그값이라 -100% 아래로도 내려가지만, 자산배수는 0에 수렴할 뿐이다.)")
    print("인버스는 k<0 — 상승 추세와 변동성 손실을 동시에 부담한다.")
    print("가정: 초과수익 mu = +30%/년 (크립토에 매우 우호적인 가정)")
    mu = 0.30
    print(f"\n{'배율':>8} " + " ".join(f"{'sigma='+pct(s):>12}" for s in (0.40, 0.55, 0.70, 1.10)))
    for k in (-2, -1, 1, 2, 3):
        row = f"{k:>+7}x "
        for sig in (0.40, 0.55, 0.70, 1.10):
            g = k * mu - k * k * sig ** 2 / 2
            row += f"{math.exp(g):>11.3f}x"
        print(row)
    print("\n해석: 변동성 55%에서 3배 레버리지는 연 -45%, 인버스(-1x)는 연 -45%다.")
    print("      인버스는 '하락에 베팅'이 아니라 '상승 추세 + 변동성 손실'을 동시에 부담한다.")
    print("      이 표는 신호의 엣지를 0으로 둔 것이 아니라, 엣지와 무관한 '구조적 비용'이다.")

# ---------------------------------------------------- CC. 청산 확률
def part_CC():
    print(); print(LINE); print("[CC] 신호 하나를 4주 보유할 때의 청산 확률")
    print("가정: 유지증거금 무시(관대한 가정) — 배율 k는 1/k 만큼 역행하면 청산.")
    print("경로 최소값 기준(반사원리 근사), 4주 보유.")
    print(f"\n{'배율':>6} {'청산 역행폭':>11} " + " ".join(f"{'sigma='+pct(s):>12}" for s in (0.40, 0.55, 0.70, 1.10)))
    for k in (2, 3, 5, 10):
        row = f"{k:>5}x {pct(1/k):>11} "
        for sig in (0.40, 0.55, 0.70, 1.10):
            s4 = sig * math.sqrt(4 / 52)
            p = min(1.0, 2 * norm_cdf(-(1 / k) / s4))
            row += f"{pct(p):>12}"
        print(row)
    print("\n해석: 알트코인 변동성(110%)에서 3배 레버리지는 신호 1회당 청산확률이 30%대다.")
    print("      10부 계산대로 신호가 8년에 한 번 나온다면, 몇 번의 신호로 계좌가 사라진다.")
    print("      청산은 '손실'이 아니라 '게임에서의 퇴출'이다 — 3부의 흡수벽이 여기 있다.")

# ------------------------------- DD. 표본 수: BTC 한 종목에 신호가 몇 번 있었나
def part_DD():
    print(); print(LINE); print("[DD] 표본 수 — BTC 역사 전체에 주봉 삼산이 몇 번 나왔는가")
    rate = 0.12          # 10부 검증 W의 실측 발생률 (개/자산/년)
    print(f"10부 실측 발생률: 주봉 삼산 {rate}개/자산/년 (약 8년에 1회)")
    print(f"\n{'대상':<34} {'가용 연수':>9} {'기대 삼산':>10} {'삼산+삼곡':>11}")
    for label, yrs, n_asset in (("BTC 1종목 (2010~)", 15, 1),
                                ("ETH 1종목 (2015~)", 10, 1),
                                ("5년 이상 알트 50개", 5, 50),
                                ("미국 주식 300개 x 20년", 20, 300)):
        exp = rate * yrs * n_asset
        print(f"{label:<34} {yrs:>8}년 {exp:>9.1f}개 {exp*2:>10.1f}개")
    print("\n해석: BTC 역사 전체를 통틀어 주봉 삼산은 기대값 2개 안팎이다.")
    print("      삼곡을 합쳐도 4개다. n=4로는 어떤 가설도 검증되지 않는다.")
    print("      '차트 의존이 강할 것'이라는 추론이 맞더라도, 그것을 확인할 표본이 없다.")

# ------------- EE. 결정적: 크립토에서 '다종목 적용'이 독립 관측을 만들어 주는가
def part_EE():
    print(); print(LINE)
    print("[EE] 10부의 해법(다종목 적용)이 크립토에서 작동하는가 — 유효표본 직접 측정")
    print("설정: 자산 80개 x 6년. 총 변동성은 60%로 '모든 구성에서 동일'하게 고정하고,")
    print("      그중 공통요인이 차지하는 비중(=평균 상관 rho)만 바꾼다.")
    print("      측정: 시뮬레이션을 50회 반복해 '신호수익 표본평균'의 실제 분산을 구하고,")
    print("            독립 가정 하 분산과 비교한다. 비율이 곧 유효표본 축소 배수다.")
    NA, DAYS, REPS, SIG_TOT = 80, 6 * 252, 50, 0.60
    print(f"\n{'구성':<26} {'rho':>6} {'평균 신호수':>11} {'표본평균 실제 SD':>16} "
          f"{'독립가정 SD':>12} {'분산팽창':>9} {'유효표본':>9}")
    for label, rho in (("크립토형 (공통요인 지배)", 0.70),
                       ("주식형 (개별요인 지배)", 0.15),
                       ("무상관 대조군", 0.00)):
        rnd = random.Random(SEED + 61)
        md = SIG_TOT * math.sqrt(rho) / math.sqrt(252)
        idd = SIG_TOT * math.sqrt(1 - rho) / math.sqrt(252)
        rep_means, rep_ns, pooled = [], [], []
        for _r in range(REPS):
            mkt = [rnd.gauss(0.0, md) for _ in range(DAYS)] if rho > 0 else [0.0] * DAYS
            rets = []
            for _a in range(NA):
                p_, closes = 100.0, []
                for t in range(DAYS):
                    p_ *= math.exp(mkt[t] + rnd.gauss(0.0, idd))
                    closes.append(p_)
                bars = to_bars(closes, 5)
                zz, cl = pivots(bars, 3), [b[2] for b in bars]
                for j in range(len(zz) - 4):
                    seq = zz[j:j+5]
                    if [x[1] for x in seq] != ['H','L','H','L','H']: continue
                    hs = [seq[0][2], seq[2][2], seq[4][2]]; ls = [seq[1][2], seq[3][2]]
                    mh = sum(hs)/3
                    if (max(hs)-min(hs))/mh > 0.04 or (mh-max(ls))/mh < 0.04: continue
                    neck = min(ls)
                    for i in range(seq[4][0]+1, min(len(bars), seq[4][0]+10)):
                        if cl[i] < neck:
                            if i + 4 < len(cl): rets.append(cl[i+4]/cl[i] - 1)
                            break
            if len(rets) >= 5:
                rep_means.append(sum(rets)/len(rets)); rep_ns.append(len(rets)); pooled += rets
        R = len(rep_means)
        gm = sum(rep_means)/R
        sd_obs = math.sqrt(sum((x-gm)**2 for x in rep_means)/(R-1))
        pm = sum(pooled)/len(pooled)
        sd_sig = math.sqrt(sum((x-pm)**2 for x in pooled)/(len(pooled)-1))
        nbar = sum(rep_ns)/R
        sd_ind = sd_sig / math.sqrt(nbar)
        infl = (sd_obs/sd_ind)**2
        print(f"{label:<26} {rho:>6.2f} {nbar:>10.1f}개 {pct(sd_obs):>16} "
              f"{pct(sd_ind):>12} {infl:>8.1f}x {nbar/infl:>8.1f}개")
    print("\n해석: 신호를 100개 모아도 '독립적인 100개'가 아니다. 공통요인이 지배하는")
    print("      크립토형에서는 표본평균의 실제 분산이 독립 가정보다 훨씬 커진다.")
    print("      = 같은 시장 움직임을 여러 자산에서 중복해 관측하고 있을 뿐이다.")
    print("      10부의 탈출구(적용 범위 확대)는 '상관이 낮을 때만' 작동한다.")
    print("      * rho는 시간에 따라 변하며 최근 알트-BTC 상관은 낮아졌다는 보고도 있다.")
    print("        따라서 이 값은 단정이 아니라, 본인이 실측해 넣어야 할 변수다.")

# ------------------------------- FF. 엣지가 진짜라고 믿어도 비중은 얼마인가
def part_FF():
    print(); print(LINE); print("[FF] 엣지가 진짜라고 믿어도, n이 작으면 적정 비중은 0에 수렴한다")
    print("가정: 신호 후 4주 수익 표준편차 15%(BTC 변동성 55% 기준), 관측된 엣지 +3%")
    sd_trade, observed = 0.15, 0.03
    prior_tau = 0.03      # '이 정도 크기의 엣지는 있을 법하다'는 사전 믿음
    print(f"사전 믿음: 엣지의 사전 표준편차 tau = {pct(prior_tau)}")
    print(f"\n{'관측 신호 수':>12} {'표준오차':>10} {'수축 후 엣지':>12} {'켈리 비중':>10} {'하프켈리':>10}")
    for n in (2, 4, 10, 30, 100):
        se = sd_trade / math.sqrt(n)
        shrink = prior_tau ** 2 / (prior_tau ** 2 + se ** 2)
        post = observed * shrink
        f = post / sd_trade ** 2
        print(f"{n:>11}개 {pct(se):>10} {pct(post):>12} {f:>9.2f}x {f/2:>9.2f}x")
    print("\n해석: n=2(=BTC 역사 전체)에서 관측된 3% 엣지의 표준오차는 10.6%다.")
    print("      엣지 자체의 3배가 넘는다. 베이지안 수축을 적용하면 3%는 0.2%로 줄고")
    print("      적정 비중은 0.1배 수준이 된다 — 레버리지의 정반대 방향이다.")
    print("      비중은 확신이 아니라 '엣지/분산'이고, 크립토는 분모가 크고 n이 작다.")

if __name__ == "__main__":
    part_AA(); part_BB(); part_CC(); part_DD(); part_EE(); part_FF()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 모형 시뮬레이션(실제 시장 데이터 아님)")
