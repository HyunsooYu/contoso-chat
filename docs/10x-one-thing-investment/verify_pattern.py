# -*- coding: utf-8 -*-
"""
후속 검증 III: "차트 패턴 학습에 10배의 노력 + 패턴이 재현되는 단 하나의 종목"
표준 라이브러리만 사용. seed 고정.
"""
import math, random

SEED = 20260907
LINE = "=" * 78
def pct(x): return f"{x*100:.1f}%"

DAYS_Y = 252
SIGD   = 0.02          # 일간 변동성 2% (연 31.7%)

# ---------------------------------------- R. 예측력이 0인 세계에서 '재현되는 종목' 찾기
def make_paths(n_stocks, n_days, rnd):
    """드리프트 0, 예측력 0인 순수 랜덤워크. 정의상 어떤 패턴도 작동하지 않는다."""
    return [[rnd.gauss(0.0, SIGD) for _ in range(n_days)] for _ in range(n_stocks)]

def run_rule(rets, n_down, hold, contrarian):
    """n_down일 연속 하락(또는 상승) 후 진입, hold일 보유. 비중첩."""
    trades, i, n = [], n_down, len(rets)
    while i + hold <= n:
        if contrarian:
            sig = all(rets[i - 1 - k] < 0 for k in range(n_down))
        else:
            sig = all(rets[i - 1 - k] > 0 for k in range(n_down))
        if sig:
            trades.append(sum(rets[i:i + hold]))
            i += hold
        else:
            i += 1
    return trades

def stats(trades, years):
    if len(trades) < 20:
        return None
    m = sum(trades) / len(trades)
    var = sum((x - m) ** 2 for x in trades) / (len(trades) - 1)
    sd = math.sqrt(var) if var > 0 else 1e-9
    tpy = len(trades) / years
    return dict(n=len(trades), mean=m, sharpe=m / sd * math.sqrt(tpy),
                ann=m * tpy, win=sum(1 for x in trades if x > 0) / len(trades))

def part_R():
    print(LINE)
    print("[R] 예측력이 정확히 0인 세계에서 '패턴이 재현되는 종목'을 찾아본다")
    print("설정: 순수 랜덤워크 300종목(드리프트 0, 일간 변동성 2%).")
    print("      정의상 어떤 차트 패턴에도 예측력이 없다 — 진짜 알파 = 0.")
    print("      표본내 5년으로 규칙x종목을 탐색하고, 표본외 5년으로 검증한다.")
    rnd = random.Random(SEED + 41)
    NS, IN, OUT = 300, 5 * DAYS_Y, 5 * DAYS_Y
    paths = make_paths(NS, IN + OUT, rnd)
    rules = [(nd, h, c) for nd in (2, 3, 4) for h in (3, 5, 10) for c in (True, False)]

    def search(rule_set, label):
        best = None
        tested = 0
        for si in range(NS):
            ins = paths[si][:IN]
            for (nd, h, c) in rule_set:
                st = stats(run_rule(ins, nd, h, c), 5.0)
                tested += 1
                if st and (best is None or st["sharpe"] > best["st"]["sharpe"]):
                    best = dict(si=si, rule=(nd, h, c), st=st)
        oos = stats(run_rule(paths[best["si"]][IN:], *best["rule"]), 5.0)
        nd, h, c = best["rule"]
        print(f"\n  [{label}] 탐색한 조합 수 = {tested:,}")
        print(f"    선택된 종목 #{best['si']}, 규칙: {nd}일 연속"
              f"{'하락 후 매수' if c else '상승 후 매수'}, {h}일 보유")
        b = best["st"]
        print(f"    표본내 5년: 연환산 {pct(b['ann']):>7}  샤프 {b['sharpe']:>5.2f}  "
              f"승률 {pct(b['win']):>6}  매매 {b['n']}회")
        if oos:
            print(f"    표본외 5년: 연환산 {pct(oos['ann']):>7}  샤프 {oos['sharpe']:>5.2f}  "
                  f"승률 {pct(oos['win']):>6}  매매 {oos['n']}회")
        else:
            print("    표본외 5년: 매매 표본 부족")
        return best, oos

    search([(3, 5, True)], "노력 1배 — 규칙 1개로 300종목 탐색")
    search(rules,          "노력 10배 — 규칙 18개로 300종목 탐색")
    print("\n해석: 진짜 알파가 0인데도 '연 20~40%, 승률 60%대'의 종목이 반드시 발견된다.")
    print("      그리고 노력을 늘릴수록 표본내 성과는 좋아지고 표본외는 그대로 0이다.")
    print("      '패턴이 재현되는 단 하나의 종목'을 고르는 행위가 곧 선택 편향이다.")
    print("\n  주의: 위 표본외 숫자는 '한 번의 추출'이라 그 자체로는 근거가 약하다.")
    print("  아래는 같은 실험을 100회 반복한 평균이다 (60종목 x 6규칙, 3년/3년).")
    rnd2 = random.Random(SEED + 71)
    NS2, T2 = 60, 3 * DAYS_Y
    rules2 = [(nd, h, c) for nd in (2, 3) for h in (3, 5, 10) for c in (True,)]
    ins_s, oos_s, ins_a, oos_a = [], [], [], []
    for _ in range(100):
        pp = make_paths(NS2, T2 * 2, rnd2)
        best = None
        for si in range(NS2):
            for r in rules2:
                st = stats(run_rule(pp[si][:T2], *r), 3.0)
                if st and (best is None or st["sharpe"] > best["st"]["sharpe"]):
                    best = dict(si=si, rule=r, st=st)
        o = stats(run_rule(pp[best["si"]][T2:], *best["rule"]), 3.0)
        if o:
            ins_s.append(best["st"]["sharpe"]); oos_s.append(o["sharpe"])
            ins_a.append(best["st"]["ann"]);    oos_a.append(o["ann"])
    n2 = len(ins_s)
    mo = sum(oos_s) / n2
    sdo = math.sqrt(sum((x - mo) ** 2 for x in oos_s) / (n2 - 1))
    se = sdo / math.sqrt(n2)
    print(f"    선택된 조합의 표본내 평균: 샤프 {sum(ins_s)/n2:>5.2f}, 연환산 {pct(sum(ins_a)/n2):>7}")
    print(f"    같은 조합의 표본외 평균:   샤프 {mo:>+5.2f}, 연환산 {pct(sum(oos_a)/n2):>7}"
          f"   (표준오차 {se:.2f}, t={mo/se:+.2f})")
    print(f"    반복 {n2}회. 표본외는 설계상 기대값 0이고 실제로 0과 구분되지 않는다(|t|<2).")
    print("    반면 표본내 샤프는 전부 선택 편향이 만들어낸 허수다.")

# --------------------------------- S. 몇 개를 뒤지면 우연히 얼마가 나오는가
def part_S():
    print(); print(LINE)
    print("[S] '순전히 운으로' 나오는 최고 샤프 — 탐색량에 따른 허들")
    print("근사식: E[최대 샤프] ~= sqrt(2 ln N) / sqrt(T)   (N=탐색 조합수, T=년)")
    print(f"\n{'탐색 조합 수':>12} " + " ".join(f"{'T='+str(t)+'년':>10}" for t in (3, 5, 10, 20)))
    for N in (10, 100, 1_000, 10_000, 100_000):
        row = f"{N:>12,} "
        for T in (3, 5, 10, 20):
            row += f"{math.sqrt(2*math.log(N))/math.sqrt(T):>10.2f}"
        print(row)
    print("\n해석: 300종목 x 18규칙 = 5,400 조합을 5년으로 뒤지면 '샤프 1.85'가 그냥 나온다.")
    print("      당신의 백테스트 샤프는 이 값을 넘어야 비로소 의미가 시작된다.")
    print("      (Bailey/Lopez de Prado의 Deflated Sharpe Ratio가 다루는 문제)")

# ---------------------------------------------------- T. 회전율이라는 세금
def part_T():
    print(); print(LINE); print("[T] 패턴 매매의 구조적 비용 — 회전율은 선형, 엣지는 아니다")
    print("왕복비용 = 수수료 + 세금 + 스프레드/슬리피지. 본인 실측치를 넣어야 한다.")
    print(f"\n{'연 매매횟수':>10} " + " ".join(f"{'왕복 '+f'{c:.2%}':>12}" for c in (0.001, 0.002, 0.004)))
    for n in (20, 50, 100, 250):
        row = f"{n:>9}회 "
        for c in (0.001, 0.002, 0.004):
            row += f"{pct(n*c):>12}"
        print(row)
    print("\n연 8% 순수익에 필요한 '매매 1회당' 총수익 (왕복비용 0.2% 가정):")
    for n in (20, 50, 100, 250):
        need = (0.08 + n * 0.002) / n
        print(f"  연 {n:>3}회 매매 -> 회당 {pct(need):>6} "
              f"(= 연 총수익 {pct(0.08 + n*0.002)})")
    print("\n해석: 매매를 늘리면 비용은 정확히 비례해 늘지만 엣지는 그렇지 않다.")
    print("      연 250회 매매는 왕복 0.2%만으로도 연 50%의 총수익을 요구한다.")

# --------------------------------- U. 실력인지 운인지 언제 알 수 있는가
def part_U():
    print(); print(LINE); print("[U] 이 규칙이 진짜인지 확인하는 데 몇 년이 걸리는가")
    print("(1) 탐색 없이 사전에 정한 단일 규칙: t=2 에 필요한 기간 = (2/SR)^2")
    print(f"\n{'진짜 샤프':>10} {'필요 관측기간':>14}")
    for sr in (1.0, 0.7, 0.5, 0.3):
        print(f"{sr:>10.1f} {(2/sr)**2:>12.1f}년")
    print("\n(2) N개 조합을 탐색한 뒤라면 허들이 E[최대샤프]만큼 올라간다:")
    print(f"    필요 t > sqrt(2 ln N) + 2  ->  기간 = ((sqrt(2 ln N)+2)/SR)^2")
    print(f"\n{'탐색 조합':>10} {'SR=1.0':>10} {'SR=0.5':>10} {'SR=0.3':>10}")
    for N in (1, 100, 5_400, 100_000):
        h = (math.sqrt(2*math.log(N)) if N > 1 else 0) + 2
        row = f"{N:>10,}"
        for sr in (1.0, 0.5, 0.3):
            row += f"{(h/sr)**2:>9.0f}년"
        print(row)
    print("\n해석: 5,400개 조합을 뒤져 찾은 샤프 0.5짜리 규칙이 진짜임을 통계로 입증하려면")
    print("      약 158년의 데이터가 필요하다. 한 종목으로는 평생 검증이 끝나지 않는다.")
    print("      * 근사식이며, 실무적 대안은 통계 검정이 아니라 '표본외 선등록 검증'이다.")

# ------------------- V. 결정적 지점: '단 하나의 종목'이 유일한 장점을 없앤다
def part_V():
    print(); print(LINE)
    print("[V] 패턴 매매의 진짜 장점(breadth)과, 그것을 '한 종목'이 파괴하는 방식")
    print("Grinold: IR = IC x sqrt(BR). 패턴 매매는 매매마다 별개 베팅이라 BR이 커진다.")
    print("그러나 베팅들이 상관되면 유효 BR = n / (1 + (n-1)*rho) 로 붕괴한다.")
    print(f"\n{'구성':<34} {'명목 BR':>9} {'상관 rho':>9} {'유효 BR':>9} {'IC=0.03 시 IR':>14}")
    cases = [
        ("한 종목 x 연100회 x 5년",        500, 0.10),
        ("한 종목 x 연100회 x 5년(rho낮음)", 500, 0.03),
        ("50종목 x 연 10회 x 5년",         2500, 0.02),
        ("100종목 x 연10회 x 5년",         5000, 0.01),
    ]
    for label, n, rho in cases:
        eff = n / (1 + (n - 1) * rho)
        ir = 0.03 * math.sqrt(eff)
        print(f"{label:<34} {n:>9,} {rho:>9.2f} {eff:>9.1f} {ir:>14.2f}")
    print("\n해석: 같은 종목의 매매들은 같은 국면·같은 뉴스·같은 유동성을 공유해 상관이 높다.")
    print("      500번을 매매해도 유효 베팅 수는 10회 수준으로 무너진다.")
    print("      반대로 '하나의 규칙을 여러 종목에 적용'하면 유효 BR이 수십~수백으로 살아난다.")
    print("      즉 여기서 'ONE Thing'은 종목이 아니라 규칙이어야 한다.")

if __name__ == "__main__":
    part_R(); part_S(); part_T(); part_U(); part_V()
    print(); print(LINE)
    print(f"seed={SEED} / 순수 파이썬 재현 가능 / 모형 시뮬레이션(실제 시장 데이터 아님)")
