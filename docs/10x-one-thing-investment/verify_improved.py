# -*- coding: utf-8 -*-
"""
12부: 가설 개선안의 개선폭을 측정한다.
핵심 아이디어 3가지를 각각 정량 검증:
  GG. 이산 패턴 -> 연속 점수 (표본 폭발)
  HH. 롱온리 -> 횡단면 중립 (상관 문제 해소)
  II. 고정 레버리지 -> 변동성 타게팅 (k*에 자동 수렴)
표준 라이브러리만 사용. seed 고정.
"""
import math, random

SEED = 20260907
LINE = "=" * 78
def pct(x): return f"{x*100:.1f}%"
def norm_pdf(z): return math.exp(-z*z/2) / math.sqrt(2*math.pi)
def norm_cdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))

# ------------------- GG. 이산 패턴 vs 연속 점수: 같은 메커니즘, 다른 측정
def part_GG():
    print(LINE)
    print("[GG] 같은 가설을 '희귀한 이산 패턴' 대신 '매주 계산하는 연속 점수'로 측정하면")
    print()
    print("전제: 삼산 가설의 '내용'은 이것이다 —")
    print("      '고점 돌파에 반복 실패한 자산은 이후 수익이 낮다'.")
    print("      삼산은 그 상태를 재는 '하나의 눈금'일 뿐, 상태 자체가 아니다.")
    print("      그래서 상태를 연속 점수 x로 재면 매주·모든 자산에서 관측할 수 있다.")
    print()
    print("주의: 이 시뮬레이션은 '메커니즘이 실제로 존재한다'고 가정하고")
    print("      어느 측정 방식이 그것을 더 빨리 검출하는지만 비교한다(검정력 비교).")
    print("      메커니즘의 존재 자체를 입증하는 것이 아니다.")

    IC_TRUE, SD_R = 0.05, 0.15          # 진짜 IC 0.05, 4주 수익 표준편차 15%
    lam = IC_TRUE * SD_R
    rnd = random.Random(SEED + 81)

    # 이산 검출: 상위 극단에서만 발화 (10부 실측 0.12개/자산/년 = 주간 0.23%)
    p_fire = 0.12 / 52
    z_cut = 2.0
    for _ in range(200):                      # 발화율 p_fire에 맞는 임계값 찾기
        z_cut = z_cut + (0.01 if (1 - norm_cdf(z_cut)) > p_fire else -0.01)
    tail_mean = norm_pdf(z_cut) / (1 - norm_cdf(z_cut))    # E[x | x > z_cut]
    edge_d = lam * tail_mean

    print(f"\n  이산(삼산): 발화율 {p_fire*52:.2f}개/자산/년, 임계 z={z_cut:.2f}")
    print(f"              신호 1회당 기대 엣지 {pct(edge_d)} (극단만 보므로 회당 엣지는 크다)")
    print(f"  연속(점수): 발화율 52개/자산/년, 관측당 IC {IC_TRUE:.2f}")

    # 검증: 20회 반복해 두 방식의 t값 분포를 비교(단일 추출의 우연을 배제)
    NA, WEEKS, REPS = 50, 52 * 6, 20
    ic_list, tc_list, td_list, nd_list = [], [], [], []
    for _rep in range(REPS):
        xs, rs = [], []
        for _a in range(NA):
            for _t in range(WEEKS):
                x = rnd.gauss(0, 1)
                xs.append(x); rs.append(-lam * x + rnd.gauss(0, SD_R))
        n_all = len(xs)
        mx = sum(xs)/n_all; mr = sum(rs)/n_all
        cov = sum((a-mx)*(b-mr) for a, b in zip(xs, rs)) / (n_all-1)
        sx = math.sqrt(sum((a-mx)**2 for a in xs)/(n_all-1))
        sr = math.sqrt(sum((b-mr)**2 for b in rs)/(n_all-1))
        ic = cov/(sx*sr)
        ic_list.append(ic); tc_list.append(ic*math.sqrt(n_all))
        fired = [b for a, b in zip(xs, rs) if a > z_cut]
        if len(fired) >= 2:
            m = sum(fired)/len(fired)
            sd = math.sqrt(sum((v-m)**2 for v in fired)/(len(fired)-1))
            td_list.append(m/(sd/math.sqrt(len(fired)))); nd_list.append(len(fired))
    print(f"\n  시뮬레이션 {REPS}회 반복 (각 50자산 x 6년 = {n_all:,}관측):")
    print(f"    연속 점수: 추정 IC 평균 {sum(ic_list)/len(ic_list):+.4f} (참값 {-IC_TRUE:+.4f}), "
          f"t 평균 {sum(tc_list)/len(tc_list):+.2f}")
    print(f"    이산 신호: 평균 {sum(nd_list)/len(nd_list):.0f}개 검출, "
          f"t 평균 {sum(td_list)/len(td_list):+.2f}")
    print(f"    -> 같은 6년 데이터에서 연속 방식만 유의성에 도달한다"
          f" (|t|>2 도달률: 연속 {sum(1 for t in tc_list if abs(t)>2)/len(tc_list)*100:.0f}%, "
          f"이산 {sum(1 for t in td_list if abs(t)>2)/len(td_list)*100:.0f}%)")
    print("\n  t=2 도달에 필요한 기간 (자산 50개 기준):")
    NA = 50
    n_c = (2 / IC_TRUE) ** 2
    n_d = (2 / (edge_d / SD_R)) ** 2
    print(f"    연속: 관측 {n_c:,.0f}개 필요 / 연 {NA*52:,}개 -> {n_c/(NA*52):.2f}년 (원시)")
    print(f"    이산: 신호 {n_d:,.0f}개 필요 / 연 {NA*0.12:.1f}개 -> {n_d/(NA*0.12):.1f}년")
    print("\n  그러나 연속 쪽에는 두 가지 감가가 붙는다 (정직하게 반영):")
    print("    · 4주 중첩 수익을 매주 관측 -> 유효표본 약 1/4")
    print("    · 자산 간 상관(11부 측정 2.1배 팽창) -> 유효표본 약 1/2.1")
    n_c_adj = n_c * 4 * 2.1
    print(f"    보정 후: {n_c_adj:,.0f}개 / 연 {NA*52:,}개 -> {n_c_adj/(NA*52):.1f}년")
    print(f"\n  결론: {n_d/(NA*0.12):.0f}년 -> {n_c_adj/(NA*52):.1f}년. 감가를 다 물려도 "
          f"{(n_d/(NA*0.12))/(n_c_adj/(NA*52)):.0f}배 빠르다.")
    print("  이유는 단순하다: 이산 패턴은 회당 엣지가 크지만 표본이 400배 적고,")
    print("  t값은 엣지에 비례하고 표본수의 제곱근에 비례하기 때문이다.")
    return n_c_adj / (NA*52), n_d / (NA*0.12)

# ---------------- HH. 롱온리 vs 횡단면 중립: 상관 문제가 실제로 해소되는가
def part_HH():
    print(); print(LINE)
    print("[HH] 횡단면 중립(롱숏)이 11부의 상관 문제를 해소하는가 — 직접 측정")
    print("설정: 자산 40개, 공통요인 상관 rho=0.70(크립토형), 총 변동성 60%.")
    print("      매주 점수 상위 20%를 매도 / 하위 20%를 매수(중립) vs 상위 20%만 매도(롱온리).")
    print("      시뮬레이션 300회 반복 -> 주간 수익 평균의 '실제 분산'을 비교한다.")
    rnd = random.Random(SEED + 91)
    NA, WEEKS, REPS, RHO = 40, 26, 300, 0.70
    sw = 0.60 / math.sqrt(52)
    sm, si = sw*math.sqrt(RHO), sw*math.sqrt(1-RHO)
    only_means, neut_means = [], []
    for _r in range(REPS):
        o_acc, n_acc = [], []
        for _w in range(WEEKS):
            mkt = rnd.gauss(0, sm)
            scores = [rnd.gauss(0, 1) for _ in range(NA)]
            rets = [mkt + rnd.gauss(0, si) for _ in range(NA)]
            order = sorted(range(NA), key=lambda i: scores[i])
            k = NA // 5
            top, bot = order[-k:], order[:k]          # 점수 상위=매도, 하위=매수
            o_acc.append(-sum(rets[i] for i in top)/k)
            n_acc.append((sum(rets[i] for i in bot) - sum(rets[i] for i in top)) / (2*k))
        only_means.append(sum(o_acc)/WEEKS)
        neut_means.append(sum(n_acc)/WEEKS)
    def stat(v):
        m = sum(v)/len(v)
        return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))
    so, sn = stat(only_means), stat(neut_means)
    print(f"\n{'구성':<22} {'주간평균의 SD':>14} {'상대 노이즈':>11}")
    print(f"{'롱온리 (상위 매도)':<22} {pct(so):>14} {so/sn:>10.1f}x")
    print(f"{'횡단면 중립 (롱숏)':<22} {pct(sn):>14} {1.0:>10.1f}x")
    print(f"\n해석: 중립화하면 같은 신호·같은 자산에서 노이즈가 {so/sn:.1f}배 줄어든다.")
    print("      공통요인(BTC 베타)이 상쇄되기 때문이다 — 11부에서 표본을 갉아먹던")
    print("      바로 그 상관이 여기서는 오히려 제거 대상이 된다.")
    print("      같은 엣지에서 t값이 그만큼 커지므로 검증 기간도 그만큼 줄어든다.")

# ------------------------- II. 고정 레버리지 vs 변동성 타게팅
def part_II():
    print(); print(LINE)
    print("[II] 고정 배율 대신 변동성 타게팅 — k*에 자동으로 수렴한다")
    print("규칙: 비중 = 목표변동성 / 실현변동성 (상한 1.0배, 레버리지 없음)")
    print("11부 검증 AA의 k* = mu/sigma^2 를 '매 시점 자동으로' 따라가는 구현이다.")
    TARGET = 0.20
    print(f"\n목표 변동성 {pct(TARGET)} 기준")
    print(f"\n{'실현 변동성':>12} {'타게팅 비중':>12} {'켈리 k*(mu=30%)':>17} {'고정 1배 대비':>14}")
    for sig in (0.20, 0.40, 0.55, 0.70, 1.10):
        w = min(1.0, TARGET/sig)
        k = 0.30/sig**2
        print(f"{pct(sig):>12} {w:>11.2f}x {k:>16.2f}x {w-1:>+13.2f}")
    print("\n해석: 변동성이 올라가면 비중이 자동으로 내려가 k*를 따라간다.")
    print("      알트 변동성 110%에서 타게팅 비중 0.18배, 켈리 0.25배 — 거의 일치한다.")
    print("      중요한 점: 이 규칙은 '엣지를 추정하지 않고도' 작동한다.")
    print("      엣지(분자)는 못 재도 변동성(분모)은 잴 수 있기 때문이다.")
    print("      11부 검증 FF가 요구한 '비중 축소'를 재량이 아니라 규칙으로 만든다.")

if __name__ == "__main__":
    part_GG(); part_HH(); part_II()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 모형 시뮬레이션(실제 시장 데이터 아님)")
