# -*- coding: utf-8 -*-
"""
'10배의 법칙'(Grant Cardone) x 'The ONE Thing'(Gary Keller) 기반 투자법 검증 스크립트.
표준 라이브러리만 사용. 결과는 seed 고정으로 재현 가능.

주의: 아래 수치는 '명시된 가정 하의 시뮬레이션 결과'이며 실제 시장 데이터가 아니다.
가정은 각 섹션 상단에 모두 노출한다.
"""
import math, random, statistics as st

SEED = 20260907
LINE = "=" * 78

def fv_annuity(S, r, n):
    """연말 S씩 n년 납입, 연 r 복리."""
    if abs(r) < 1e-12:
        return S * n
    return S * ((1 + r) ** n - 1) / r

def bisect(f, lo, hi, tol=1e-10):
    flo = f(lo)
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2

# ---------------------------------------------------------------- A. 10배 목표
def part_A():
    print(LINE); print("[A] '10배 목표'는 수익률로 달성 가능한가")
    print("가정: 연 저축액 1(단위), 기준 수익률 7%, 목표 = 기준안 최종자산의 10배")
    print(f"{'기간':>6} {'기준 최종자산':>14} {'필요 수익률':>12} {'대안: 저축배수':>14}")
    for n in (10, 20, 30, 40):
        base = fv_annuity(1.0, 0.07, n)
        target = 10 * base
        r_req = bisect(lambda r: fv_annuity(1.0, r, n) - target, 0.07, 3.0)
        print(f"{n:>4}년 {base:>14.2f} {r_req*100:>11.1f}% {10.0:>13.1f}x")
    print("해석: 목표를 10배로 올리면 필요 수익률은 '10배'가 아니라 비선형으로 폭증한다.")
    print("      반면 저축액 10배는 정확히 10배 결과를 준다(선형·확정적).")

# ------------------------------------------------- B. ONE Thing 식별(민감도)
def part_B():
    print(); print(LINE); print("[B] 최종자산에 대한 입력변수 탄력성 = 'ONE Thing' 후보 검정")
    print("가정: 연 저축 1, 총수익률 7%, 보수 0.5% -> 순수익률 6.5%. 각 변수를 +10% 상대변화")
    print(f"{'기간':>6} {'저축액+10%':>12} {'수익률+10%':>12} {'기간+10%':>11} {'보수-10%':>11}")
    S, g, fee = 1.0, 0.07, 0.005
    for n in (10, 20, 30, 40):
        base = fv_annuity(S, g - fee, n)
        d_S  = fv_annuity(S * 1.1, g - fee, n) / base - 1
        d_r  = fv_annuity(S, g * 1.1 - fee, n) / base - 1
        d_n  = fv_annuity(S, g - fee, n * 1.1) / base - 1
        d_f  = fv_annuity(S, g - fee * 0.9, n) / base - 1
        print(f"{n:>4}년 {d_S*100:>11.1f}% {d_r*100:>11.1f}% {d_n*100:>10.1f}% {d_f*100:>10.1f}%")
    print("해석: 10년 구간의 ONE Thing은 '저축액', 25년 이후의 ONE Thing은 '수익률x기간'.")
    print("      즉 ONE Thing은 고정 상수가 아니라 '남은 기간'의 함수다.")

# ------------------------------------------------------------- C. 비용/행동격차
def part_C():
    print(); print(LINE); print("[C] 도미노 하단: 비용과 행동격차의 30년 누적 효과")
    print("가정: 원금 1 일시납, 총수익률 7%, 30년")
    base = 1.07 ** 30
    for label, drag in (("보수 0.2% (인덱스)", 0.002), ("보수 1.0% (액티브)", 0.010),
                        ("행동격차 1.2% (M* 2025)", 0.012), ("보수1.0%+행동1.2%", 0.022)):
        v = (1.07 - drag) ** 30
        print(f"  {label:<20} 최종 {v:>6.2f}x  (무비용 {base:.2f}x 대비 {(v/base-1)*100:>6.1f}%)")
    print("해석: 연 2%p 남짓의 누수가 30년 뒤 최종자산의 40% 이상을 가져간다.")
    print("      '수익률 2%p 추가 획득'보다 '2%p 누수 차단'이 확실성이 훨씬 높다.")
    print("      단, 행동격차 1.2%p의 크기는 학계에서 논쟁 중(Fulkerson et al., FAJ 2026 반론).")

# ------------------------------------------------------------------ D. 레버리지
def part_D():
    print(); print(LINE); print("[D] '10배 행동'을 레버리지로 번역했을 때 (핵심 반증)")
    mu_ex, sig, rf, spread = 0.06, 0.18, 0.03, 0.015
    print(f"가정: 초과수익(산술) {mu_ex:.0%}, 변동성 {sig:.0%}, 무위험 {rf:.0%}, 조달가산 {spread:.1%}")
    print(f"      월단위 리밸런싱, 30년, 경로 {10000}개, 파산 = 원금의 10% 미만 도달")
    k_star = mu_ex / sig ** 2
    print(f"이론 최적 배율(Kelly) k* = mu/sigma^2 = {k_star:.2f}x  (하프켈리 {k_star/2:.2f}x)")

    random.seed(SEED)
    N, months = 10000, 360
    dt = 1 / 12
    paths = [[random.gauss((rf + mu_ex) * dt, sig * math.sqrt(dt)) for _ in range(months)]
             for _ in range(N)]
    print(f"\n{'배율':>5} {'중앙값 최종':>12} {'중앙 CAGR':>10} {'하위5%':>9} {'파산확률':>9} {'1x초과확률':>11}")
    base_finals = None
    for k in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
        finals, ruins = [], 0
        for p in paths:
            w, ruined, peak_floor = 1.0, False, 0.10
            for r in p:
                lev_r = k * r - (k - 1) * rf * dt          # 조달비용 차감
                if k > 1:
                    lev_r -= (k - 1) * spread * dt
                w *= (1 + lev_r)
                if w <= peak_floor:
                    w, ruined = 0.0, True
                    break
            if ruined:
                ruins += 1
            finals.append(w)
        finals_sorted = sorted(finals)
        med = finals_sorted[N // 2]
        p5 = finals_sorted[int(N * 0.05)]
        cagr = (med ** (1 / 30) - 1) if med > 0 else -1.0
        if k == 1.0:
            base_finals = finals
            beat = float('nan')
            beat_s = "     기준"
        else:
            beat = sum(1 for a, b in zip(finals, base_finals) if a > b) / N
            beat_s = f"{beat*100:>10.1f}%"
        print(f"{k:>4.1f}x {med:>12.2f} {cagr*100:>9.1f}% {p5:>9.2f} {ruins/N*100:>8.1f}% {beat_s}")
    print("해석: 기대수익은 k에 선형이지만 변동성 손실은 k^2에 비례한다(g ~ k*mu - k^2*sigma^2/2).")
    print("      배율 10x는 '10배의 결과'가 아니라 '확정적 파산'을 만든다. 규모의 법칙은")
    print("      승산이 양(+)인 곳에만 적용되고, 레버리지는 승산 자체를 음(-)으로 뒤집는다.")

# ------------------------------------------------------------------- E. 집중
def part_E():
    print(); print(LINE); print("[E] 'ONE Thing'을 종목 집중으로 번역했을 때 (두 번째 반증)")
    print("가정: 시장 로그수익 ~ N(6%, 16%), 개별 고유수익 ~ N(-4.5%, 30%) [산술기대는 시장과 동일]")
    print("      연 1% 상장폐지/전액손실 해저드, 30년, 매년 동일비중 리밸런싱, 경로 10000개")
    random.seed(SEED + 1)
    N, years, hazard = 10000, 30, 0.01
    sizes = (1, 3, 10, 30)
    res = {n: [] for n in sizes}
    mkt = []
    for _ in range(N):
        ms = [random.gauss(0.06, 0.16) for _ in range(years)]
        # 시장(광범위 분산)도 동일한 상장폐지 손실을 겪는다: 비교 기준을 맞춘다
        mkt.append(math.exp(sum(ms)) * (1 - hazard) ** years)
        for n in sizes:
            w = 1.0
            for y in range(years):
                if w <= 0:
                    break
                gross = 0.0
                for _i in range(n):
                    if random.random() < hazard:
                        continue          # 해당 종목 슬라이스 전액 손실
                    gross += math.exp(ms[y] + random.gauss(-0.045, 0.30))
                w *= gross / n            # 매년 남은 자본을 n개에 동일비중 재배분
            res[n].append(w)
    mkt_sorted = sorted(mkt)
    print(f"\n{'종목수':>6} {'중앙값':>9} {'평균':>9} {'하위5%':>8} {'90%손실':>9} {'시장미달확률':>13}")
    for n in sizes:
        v = sorted(res[n])
        med, avg, p5 = v[N // 2], sum(v) / N, v[int(N * 0.05)]
        wipe = sum(1 for x in v if x < 0.1) / N
        under = sum(1 for a, b in zip(res[n], mkt) if a < b) / N
        print(f"{n:>5}개 {med:>9.2f} {avg:>9.2f} {p5:>8.2f} {wipe*100:>8.1f}% {under*100:>12.1f}%")
    print(f"{'분산시장':>5} {mkt_sorted[N//2]:>9.2f} {sum(mkt)/N:>9.2f} {mkt_sorted[int(N*0.05)]:>8.2f} "
          f"{sum(1 for x in mkt if x < 0.1)/N*100:>8.1f}% {'-':>12}")
    print("해석: 평균은 종목수와 무관하지만 중앙값은 집중할수록 붕괴한다(양의 왜도).")
    print("      '한 곳에 몰아라'는 실력 우위가 입증된 경우에만 성립하는 조건부 명제다.")

# ------------------------------------------------- F. 노력 -> 결과 전달함수
def part_F():
    print(); print(LINE); print("[F] '10배 행동'은 어디에 투입해야 하는가")
    print("가정: 연소득 100, 저축률 20%(=20), 순수익률 6.5%, 30년")
    S0, r, n = 20.0, 0.065, 30
    base = fv_annuity(S0, r, n)
    scenarios = [
        ("기준안", S0, r),
        ("리서치 10배 -> 알파 +1%p (비용 0)", S0, r + 0.01),
        ("리서치 10배 -> 알파 +1%p, 회전비용 -1.2%p", S0, r - 0.002),
        ("소득 +50% 전액 저축 (저축 20->70)", 70.0, r),
        ("저축률 20%->30% (저축 20->30)", 30.0, r),
    ]
    for label, S, rr in scenarios:
        v = fv_annuity(S, rr, n)
        print(f"  {label:<38} 최종 {v:>9.1f}  ({v/base:>5.2f}x)")
    print("해석: '노력 -> 결과' 전달함수의 기울기가 큰 쪽은 시장(알파)이 아니라 소득/저축이다.")
    print("      10배의 법칙은 통제 가능한 입력에 걸었을 때만 살아남는다.")

if __name__ == "__main__":
    part_A(); part_B(); part_C(); part_D(); part_E(); part_F()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 실제 시장 데이터 아님(모형 시뮬레이션)")
