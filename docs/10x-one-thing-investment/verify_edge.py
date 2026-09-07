# -*- coding: utf-8 -*-
"""
후속 검증: '10배 리서치 + 단 하나의 종목' 해석은 성립하는가?
= 집중이 정당화되려면 필요한 '실력의 크기'를 역산한다.
표준 라이브러리만 사용. seed 고정.
"""
import math, random

SEED = 20260907
LINE = "=" * 78
YEARS = 30
NPATH = 6000
SIG_M = 0.16      # 시장 로그 변동성
MU_M  = 0.06      # 시장 로그 수익
SIG_I = 0.30      # 개별 고유 변동성
HAZ   = 0.01      # 연 상장폐지/전액손실 확률

def pct(x): return f"{x*100:.1f}%"

# ---------------------------------------------- G. 집중을 정당화하는 손익분기 알파
def part_G():
    print(LINE); print("[G] 집중이 시장을 이기려면 얼마의 알파가 필요한가")
    print(f"가정: 시장 logN({MU_M:.0%},{SIG_M:.0%}), 고유 변동성 {SIG_I:.0%}, 해저드 {HAZ:.0%}/년,")
    print(f"      {YEARS}년, 경로 {NPATH}, 알파는 '지속되는 연 초과수익(산술)'")
    print("이론 예측: 손익분기 알파 ~= 고유분산/(2N) + 해저드 = "
          f"{SIG_I**2/2*100:.1f}%/N + {HAZ*100:.0f}%")

    alphas = (0.00, 0.02, 0.04, 0.06, 0.09)
    sizes  = (1, 3, 5, 10)
    MAXN = max(sizes)
    random.seed(SEED + 7)

    med_acc = {(n, a): [] for n in sizes for a in alphas}
    beat_acc = {(n, a): 0 for n in sizes for a in alphas}
    mkt_all = []

    base_mu_i = -SIG_I ** 2 / 2      # E[exp(eps)] = 1 (알파 0 기준)
    for _ in range(NPATH):
        e_m = [math.exp(random.gauss(MU_M, SIG_M)) for _ in range(YEARS)]
        e_i = [[math.exp(random.gauss(base_mu_i, SIG_I)) for _ in range(MAXN)]
               for _ in range(YEARS)]
        alive = [[0.0 if random.random() < HAZ else 1.0 for _ in range(MAXN)]
                 for _ in range(YEARS)]
        mkt = 1.0
        for y in range(YEARS):
            mkt *= e_m[y] * (1 - HAZ)     # 분산시장도 동일 해저드 손실 반영
        mkt_all.append(mkt)
        for n in sizes:
            for a in alphas:
                w = 1.0
                for y in range(YEARS):
                    if w <= 0.0:
                        break
                    s = 0.0
                    for i in range(n):
                        s += e_i[y][i] * alive[y][i]
                    w *= e_m[y] * (1 + a) * s / n
                med_acc[(n, a)].append(w)
                if w > mkt:
                    beat_acc[(n, a)] += 1

    mkt_med = sorted(mkt_all)[NPATH // 2]
    print(f"\n시장(분산) 중앙값 = {mkt_med:.2f}배\n")
    print("  중앙값 최종자산 (괄호=시장 초과확률)")
    hdr = "  종목수 " + " ".join(f"{'a='+format(a*100,'.0f')+'%':>16}" for a in alphas)
    print(hdr)
    for n in sizes:
        row = f"  {n:>4}개 "
        for a in alphas:
            v = sorted(med_acc[(n, a)])[NPATH // 2]
            b = beat_acc[(n, a)] / NPATH
            mark = "*" if v >= mkt_med else " "
            row += f"{v:>9.2f}{mark}({pct(b):>5}) "
        print(row)
    print("  * = 시장 중앙값 이상 (손익분기 통과)")
    print("\n해석: 손익분기 알파는 종목수에 반비례한다. 1종목은 연 ~5-6%p의 '지속' 알파가")
    print("      있어야 겨우 본전이고, 5종목이면 ~2%p면 된다. 집중의 대가는 실력 요구량이다.")

# ------------------------------------------- H. 기본법칙: 리서치 10배 -> IC 7배?
def part_H():
    print(); print(LINE); print("[H] Grinold 기본법칙 — 집중이 요구하는 '예측력 배수'")
    print("IR = IC x sqrt(BR).  같은 IR을 유지하며 종목수를 줄이려면 IC가 sqrt(배수)만큼 커져야 한다.")
    print(f"\n{'집중 종목수':>10} {'필요 IC 배수':>12} {'IC=0.05 대비 필요 IC':>22} {'현실성':>10}")
    for n in (50, 20, 10, 5, 3, 1):
        mult = math.sqrt(50 / n)
        need = 0.05 * mult
        real = "일반적" if need <= 0.08 else ("상위권" if need <= 0.15 else "관측된 바 거의 없음")
        print(f"{n:>9}개 {mult:>11.2f}x {need:>21.3f} {real:>12}")
    print("\n해석: 50종목(IC 0.05)과 같은 정보비율을 1종목으로 내려면 IC 0.354가 필요하다.")
    print("      IC 0.354 = 내 예측과 실현수익의 상관계수 0.35. 우수 운용자도 0.05~0.10 수준이다.")
    print("      '리서치 10배'가 IC를 7배 올린다는 근거는 없다 — 리서치는 IC를 선형으로 올리지")
    print("      않고, 경쟁자도 같은 리서치를 하기 때문이다.")

# ------------------------------- I. 같은 알파를 두 방식으로 달성했을 때
def part_I():
    print(); print(LINE)
    print("[I] '같은 크기의 알파'를 승자 찾기 / 패자 피하기로 달성했을 때 (공정 비교)")
    def norm_cdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
    def norm_ppf(p):
        lo, hi = -8.0, 8.0
        for _ in range(200):
            mid = (lo + hi) / 2
            if norm_cdf(mid) < p: lo = mid
            else: hi = mid
        return (lo + hi) / 2
    # 하위 절단점 c 에서의 알파 배수 = Phi(sigma - c) / Phi(-c)
    def alpha_from_cut(c): return norm_cdf(SIG_I - c) / norm_cdf(-c)
    TARGET = 0.02
    lo, hi = -6.0, 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if alpha_from_cut(mid) < 1 + TARGET: lo = mid   # alpha는 c에 대해 증가함수
        else: hi = mid
    CUT = (lo + hi) / 2
    q = norm_cdf(CUT)
    print(f"가정: 5종목 집중, {YEARS}년, 경로 {NPATH}, 두 방식 모두 산술 알파 +{TARGET:.0%}로 통일")
    print(f"      '패자 피하기'의 정의: 최악 하위 {q*100:.1f}% 종목을 매수하지 않는 능력")
    print(f"      (= 이 절단만으로 알파가 정확히 +{TARGET:.0%}가 된다)")

    random.seed(SEED + 11)
    N = 5
    base_mu_i = -SIG_I ** 2 / 2
    scen = {
        "리서치 없음":                    dict(a=0.00, haz=HAZ,   cut=None),
        "승자 찾기 (분포 전체 +2%p)":     dict(a=TARGET, haz=HAZ, cut=None),
        f"패자 피하기 (하위 {q*100:.1f}% 배제)": dict(a=0.00, haz=HAZ, cut=CUT),
        "파산 회피 (해저드 1%->0.2%)":    dict(a=0.00, haz=0.002, cut=None),
        "패자 배제 + 파산 회피":          dict(a=0.00, haz=0.002, cut=CUT),
    }
    print(f"\n{'시나리오':<32} {'중앙값':>8} {'평균':>8} {'하위5%':>8} {'시장초과':>9}")
    mkt_all, results, beats = [], {k: [] for k in scen}, {k: 0 for k in scen}
    for _ in range(NPATH):
        ms = [random.gauss(MU_M, SIG_M) for _ in range(YEARS)]
        mkt = math.exp(sum(ms)) * (1 - HAZ) ** YEARS
        mkt_all.append(mkt)
        for name, cfg in scen.items():
            w = 1.0
            for y in range(YEARS):
                if w <= 0.0: break
                s_ = 0.0
                for _i in range(N):
                    if random.random() < cfg["haz"]:
                        continue
                    z = random.gauss(0, 1)
                    if cfg["cut"] is not None:
                        while z < cfg["cut"]:
                            z = random.gauss(0, 1)
                    s_ += math.exp(base_mu_i + SIG_I * z)
                w *= math.exp(ms[y]) * (1 + cfg["a"]) * s_ / N
            results[name].append(w)
            if w > mkt: beats[name] += 1
    for name in scen:
        v = sorted(results[name])
        print(f"{name:<32} {v[NPATH//2]:>8.2f} {sum(v)/NPATH:>8.2f} "
              f"{v[int(NPATH*0.05)]:>8.2f} {pct(beats[name]/NPATH):>9}")
    print(f"{'분산시장(기준)':<32} {sorted(mkt_all)[NPATH//2]:>8.2f} "
          f"{sum(mkt_all)/NPATH:>8.2f} {sorted(mkt_all)[int(NPATH*0.05)]:>8.2f} {'-':>9}")
    print("\n해석: 알파의 크기가 같아도 '패자 배제' 쪽이 중앙값과 하위 5%에서 앞선다.")
    print("      왼쪽 꼬리를 자르면 변동성 손실이 줄어 같은 산술수익이 더 큰 기하수익이 된다.")
    print(f"      그리고 요구되는 능력이 현실적이다 — 하위 {q*100:.1f}%의 지뢰만 걸러내면 된다.")

# ------------------------------------------------- J. 실력이 있어도 얼마나 걸까
def part_J():
    print(); print(LINE); print("[J] 알파가 진짜라면, 그 종목에 얼마를 넣어야 하는가 (켈리)")
    print(f"최적 초과비중 w* = alpha / 고유분산.  고유변동성 {SIG_I:.0%} -> 고유분산 {SIG_I**2:.2%}")
    print(f"\n{'진짜 알파':>10} {'w* (풀켈리)':>13} {'하프켈리':>10} {'100% 몰빵 시 기하수익':>22}")
    for a in (0.02, 0.03, 0.05, 0.09, 0.12):
        w = a / SIG_I ** 2
        g_full = 1.0 * a - 1.0 ** 2 * SIG_I ** 2 / 2
        print(f"{pct(a):>10} {w:>12.2f} {w/2:>10.2f} {pct(g_full):>22}")
    print(f"\n100% 몰빵이 최적이 되는 조건: alpha >= 고유분산 = {SIG_I**2:.1%}/년 (지속적으로)")
    print("\n추정오차의 대가 (알파를 실제의 2배로 착각한 경우):")
    for a_true, a_belief in ((0.03, 0.06), (0.045, 0.09)):
        w = a_belief / SIG_I ** 2
        g = w * a_true - w ** 2 * SIG_I ** 2 / 2
        g_opt = (a_true / SIG_I ** 2) * a_true - (a_true / SIG_I ** 2) ** 2 * SIG_I ** 2 / 2
        print(f"  진짜 {pct(a_true)}인데 {pct(a_belief)}로 믿음 -> 비중 {w:.2f}, "
              f"기하수익 {pct(g)} (최적 {pct(g_opt)})")
    print("\n해석: 리서치가 벌어주는 것은 '몰빵할 권리'가 아니라 '포지션 크기'다.")
    print("      알파를 2배로 과대평가하면 초과수익이 통째로 사라진다.")

# --------------------------------------- K. 리서치 시간의 손익분기 자본금
def part_K():
    print(); print(LINE); print("[K] '리서치 10배'의 손익분기 자본금")
    print("리서치의 가치 = 알파 x 자본. 시간은 자본에 비례해 값이 커진다.")
    print("가정: 리서치 1,000시간/년(주 20시간), 기회비용 시급 30,000원 -> 연 3,000만원")
    cost = 1000 * 30000
    print(f"\n{'달성 알파':>10} {'손익분기 자본금':>18} {'자본 1억일 때 시급':>20}")
    for a in (0.01, 0.02, 0.03, 0.05, 0.09):
        breakeven = cost / a
        hourly = 1_0000_0000 * a / 1000
        print(f"{pct(a):>10} {breakeven/1_0000_0000:>15.1f}억원 {hourly:>17,.0f}원")
    print("\n해석: 자본 1억, 알파 3%면 리서치 시급 3,000원이다. 같은 1,000시간을 소득 증대에")
    print("      쓰면 훨씬 크다. 리서치 10배는 '자본이 충분히 커진 뒤'의 전략이다.")
    print("      즉 도미노 순서상 리서치는 여전히 마지막 조각이다.")

if __name__ == "__main__":
    part_G(); part_H(); part_I(); part_J(); part_K()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 모형 시뮬레이션(실제 시장 데이터 아님)")
