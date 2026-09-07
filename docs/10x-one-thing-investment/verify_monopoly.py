# -*- coding: utf-8 -*-
"""
후속 검증 II: "10년 뒤 유망 산업의 독점기업이면 하나에 집중할 만하지 않은가?"
= 이 논지를 통과해야 하는 관문으로 분해하고 각각을 계산한다.
표준 라이브러리만 사용. seed 고정.
"""
import math, random

SEED = 20260907
LINE = "=" * 78
def pct(x): return f"{x*100:.1f}%"

# ------------------------------------------------------ M. 관문 분해
def part_M():
    print(LINE); print("[M] 이 논지가 돈을 벌려면 몇 개의 관문을 통과해야 하는가")
    gates = [
        "① 10년 뒤 그 산업이 실제로 커진다",
        "② 그 기업이 10년 뒤에도 지배자로 남는다",
        "③ 그 성장이 현재 주가에 아직 반영돼 있지 않다",
        "④ 나는 중간의 -70% 구간을 팔지 않고 견딘다",
    ]
    for g in gates: print("   " + g)
    print("\n네 관문은 모두 통과해야 하므로 확률이 곱해진다.")
    print(f"\n{'각 관문 확신도':>14} {'통과 확률(4중 곱)':>18}")
    for p in (0.95, 0.90, 0.85, 0.80, 0.70, 0.60):
        print(f"{pct(p):>14} {pct(p**4):>18}")
    need = 0.5 ** 0.25
    print(f"\n합산 성공확률 50%를 만들려면 관문마다 {pct(need)}의 확신이 필요하다.")
    print("주의: ①만 맞히는 것과 ①~④를 모두 맞히는 것은 전혀 다른 문제다.")
    print("      대부분의 '유망 산업' 논의는 ①에서 멈추고 ②③④를 건너뛴다.")

# ------------------------------------- N. 이미 가격에 반영된 성장 (멀티플 압축)
def part_N():
    print(); print(LINE); print("[N] '유망 독점기업'의 숨은 세금 — 멀티플 압축")
    print("10년 수익률 = EPS 성장 x (청산 PER / 진입 PER).  배당 0 가정.")
    print("독점·유망 = 이미 높은 PER. 성장이 정상화되면 PER은 반드시 내려온다.")
    cagrs = (0.08, 0.12, 0.15, 0.20, 0.25, 0.30)
    for entry in (25, 40, 60):
        print(f"\n  진입 PER {entry}배 — 10년 연평균 수익률")
        hdr = "   EPS CAGR " + " ".join(f"{'청산PER '+str(x):>12}" for x in (15, 20, 30))
        print(hdr)
        for g in cagrs:
            row = f"   {pct(g):>9} "
            for exitpe in (15, 20, 30):
                total = (1 + g) ** 10 * (exitpe / entry)
                ann = total ** 0.1 - 1
                mark = "*" if ann >= 0.08 else " "
                row += f"{pct(ann):>11}{mark} "
            print(row)
    print("\n  * = 연 8%(시장 수준) 이상")
    print("\n손익분기 EPS 성장률 (연 8% 달성에 필요):")
    for entry, exitpe in ((40, 20), (40, 15), (60, 20), (25, 20)):
        need = (1.08 ** 10 * entry / exitpe) ** 0.1 - 1
        print(f"  진입 PER {entry} -> 청산 PER {exitpe}: 연 {pct(need)} 를 10년 내내")
    print("\n해석: 진입 PER 40 -> 청산 20이면 10년간 EPS를 연 15.7%씩 늘려야 '겨우 시장만큼'이다.")
    print("      당신의 수익은 '기업이 얼마나 성장하느냐'가 아니라")
    print("      '시장이 이미 기대한 것보다 얼마나 더 성장하느냐'에서 나온다.")

# --------------------------------------------- O. -70% 구간을 견딜 수 있는가
def part_O():
    print(); print(LINE); print("[O] 승자에 올라타도 중간을 견뎌야 한다")
    print("가정: 뛰어난 성장주 로그수익 N(12%, 45%), 10년, 월단위, 경로 10000")
    random.seed(SEED + 21)
    N, months = 10000, 120
    dt = 1/12
    mu, sig = 0.12, 0.45
    dd_counts = {0.3: 0, 0.5: 0, 0.7: 0, 0.8: 0}
    finals, finals_cap = [], []
    CAP = 0.60   # 고점 대비 -60%에서 이탈하는 투자자
    for _ in range(N):
        w, peak = 1.0, 1.0
        maxdd, capped, w_cap = 0.0, False, None
        for _m in range(months):
            w *= math.exp(random.gauss(mu*dt - 0.0, sig*math.sqrt(dt)))
            peak = max(peak, w)
            dd = 1 - w/peak
            maxdd = max(maxdd, dd)
            if not capped and dd >= CAP:
                capped, w_cap = True, w      # 이 시점에 팔고 시장(연 7%)으로 이동
        for k in dd_counts:
            if maxdd >= k: dd_counts[k] += 1
        finals.append(w)
        finals_cap.append(w_cap * 1.07 ** 5 if capped else w)  # 잔여기간 평균 5년 가정
    print(f"\n{'최대낙폭':>10} {'발생 확률':>10}")
    for k in sorted(dd_counts):
        print(f"{'-'+pct(k):>10} {pct(dd_counts[k]/N):>10}")
    fs, fc = sorted(finals), sorted(finals_cap)
    print(f"\n끝까지 보유:      중앙값 {fs[N//2]:.2f}배, 평균 {sum(fs)/N:.2f}배")
    print(f"-60%에서 이탈:    중앙값 {fc[N//2]:.2f}배, 평균 {sum(fc)/N:.2f}배")
    print(f"이탈로 잃은 평균 수익: {(sum(fs)-sum(fc))/N:.2f}배분")
    print("\n해석: 관문 ④는 심리가 아니라 확률이다. 이 변동성에서 -50% 이상 낙폭은")
    print("      거의 확실히 온다. 실제 대형 승자들의 역사적 낙폭도 같은 범위였다")
    print("      (아마존은 2000~01년 고점 대비 약 -94%를 겪고 나서 승자가 되었다).")

# ------------------------- P. 산업 예측이 '맞았는데도' 종목이 틀리는 경우 (핵심)
def part_P():
    print(); print(LINE)
    print("[P] 산업 예측이 100% 적중했다고 가정해도 — 승자를 골랐는가는 별개다")
    print("가정: 후보 기업 10개, 모두 같은 밸류에이션에 진입. 산업은 10년 뒤")
    print("      진입 시가총액 합계의 8배가 된다(대성공). 단 점유는 승자독식으로 분배.")
    print("      점유율 ~ 로그정규(sigma=1.2) 정규화, 연 3% 도산 해저드")
    print("      (도산 기업의 몫은 생존자에게 이전 — 산업 총가치 8배는 보장된다.")
    print("       즉 이 모형은 산업 논지에 최대한 유리하게 설정돼 있다)")
    random.seed(SEED + 31)
    NP, K, YEARS = 10000, 10, 10
    INDUSTRY_MULT = 8.0
    res = {n: [] for n in (1, 3, 5, 10)}
    for _ in range(NP):
        survive = [1.0 if random.random() > (1 - (1-0.03)**YEARS) else 0.0 for _ in range(K)]
        raw = [math.exp(random.gauss(0, 1.2)) * survive[i] for i in range(K)]
        tot = sum(raw)
        if tot <= 0:
            shares = [0.0]*K
        else:
            shares = [x/tot for x in raw]
        # 기업 i 종가 = 산업 총가치 x 점유율.  진입가 = 각 1 (총 K)
        vals = [INDUSTRY_MULT * K * s for s in shares]
        random.shuffle(vals)                 # 어느 기업이 승자일지 사전에 모름
        for n in (1, 3, 5, 10):
            res[n].append(sum(vals[:n]) / n)
    print(f"\n산업 전체(10개 균등 보유) = {INDUSTRY_MULT:.1f}배 확정\n")
    print(f"{'보유 종목수':>12} {'중앙값':>9} {'평균':>9} {'하위25%':>9} {'산업 미달확률':>14}")
    for n in (1, 3, 5, 10):
        v = sorted(res[n])
        under = sum(1 for x in res[n] if x < INDUSTRY_MULT * (1 - 1e-9)) / NP
        print(f"{n:>10}개 {v[NP//2]:>9.2f} {sum(v)/NP:>9.2f} "
              f"{v[int(NP*0.25)]:>9.2f} {pct(under):>14}")
    print("\n해석: 산업 예측이 완벽하게 맞아도 1종목 선택의 중앙값은 산업 전체의")
    print("      절반에도 못 미치고, 산업에 지는 확률이 압도적이다.")
    print("      '어떤 산업이 큰다'와 '어느 기업이 그 가치를 가져간다'는 다른 예측이다.")
    print("      전자만 맞혔다면 정답은 그 산업 바스켓이지 그 안의 한 종목이 아니다.")

# ------------------------------------------------- Q. 합산: 두 논지의 결합
def part_Q():
    print(); print(LINE); print("[Q] 종합 — 같은 확신을 어디에 실을 것인가")
    print("관문 통과확률(M, 관문당 85%) x 종목선택(P, 1종목 vs 5종목)")
    p_gate = 0.85 ** 3          # ①②③ (④는 아래 보유규율로 별도)
    print(f"\n  ①②③ 통과확률(관문당 85%) = {pct(p_gate)}")
    print(f"  여기에 P의 결과를 곱하면:")
    print(f"    1종목 집중  : {pct(p_gate)} x (산업 적중 시에도 중앙값 열위) -> 기대 중앙값 붕괴")
    print(f"    5종목 바스켓: {pct(p_gate)} x (산업 적중 시 중앙값 보존)   -> 논지가 살아남음")
    print("\n결론: '유망 산업 독점기업' 논지의 올바른 실행 형태는")
    print("      '그 산업의 상위 3~7개 바스켓 + 비중 상한'이지 '단 하나의 종목'이 아니다.")
    print("      단일 종목은 산업 논지에 '종목 선택'이라는 별개의 베팅을 공짜로 얹는 것이다.")

if __name__ == "__main__":
    part_M(); part_N(); part_O(); part_P(); part_Q()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 모형 시뮬레이션(실제 시장 데이터 아님)")
