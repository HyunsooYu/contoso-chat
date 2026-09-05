"""시나리오 엔진.

초안 결함 A-5의 해결:
  초안의 5개 시나리오는 서로 독립적인 조합이었다. 그런데 실제로는
  **금리↑ + 자산가격↓ + 소득충격 + 역전세가 같이 온다.**
  독립 시나리오로 돌리면 진짜 위험한 꼬리를 절대 못 본다.

그래서 두 층으로 나눈다:
  - 결정론 시나리오: **설명용**. 사람이 이해할 수 있는 이야기.
  - 상관 몬테카를로: **의사결정용**. 목적함수는 기대값 최대화가 아니라
    하방 제약이다. 육아 가정에서 최적화 대상은 기대수익이 아니라
    "아이 학기 중에 원치 않는 이사를 하게 될 확률"이다.

의존성 없이(numpy 없이) Cholesky 분해를 직접 구현한다.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from fde.housing import assess_deposit_risk
from fde.models import Assumptions, FamilyState
from fde.options import Path
from fde.policy import PolicySet


# ================================================================== 선형대수


def cholesky(m: list[list[float]], ridge: float = 1e-10) -> list[list[float]]:
    """하삼각 L (m = L·Lᵀ). 양정치가 아니면 대각에 ridge 를 키워가며 재시도."""
    n = len(m)
    for attempt in range(8):
        eps = ridge * (10.0**attempt)
        a = [[m[i][j] + (eps if i == j else 0.0) for j in range(n)] for i in range(n)]
        L = [[0.0] * n for _ in range(n)]
        ok = True
        for i in range(n):
            for j in range(i + 1):
                ssum = sum(L[i][k] * L[j][k] for k in range(j))
                if i == j:
                    val = a[i][i] - ssum
                    if val <= 0:
                        ok = False
                        break
                    L[i][j] = math.sqrt(val)
                else:
                    L[i][j] = (a[i][j] - ssum) / L[j][j]
            if not ok:
                break
        if ok:
            return L
    raise ValueError("상관행렬을 양정치로 만들 수 없습니다. 상관계수를 확인하세요.")


def _correlate(L: list[list[float]], z: list[float]) -> list[float]:
    n = len(L)
    return [sum(L[i][k] * z[k] for k in range(i + 1)) for i in range(n)]


def correlation_matrix(a: Assumptions) -> list[list[float]]:
    """[house, jeonse, rate, income] 상관행렬."""
    hj, hr, jr, hi = (
        a.corr_house_jeonse, a.corr_house_rate, a.corr_jeonse_rate, a.corr_house_income
    )
    # jeonse-income, rate-income 은 직접 지정하지 않고 합리적으로 유도
    ji = hi * hj
    ri = hr * hi
    return [
        [1.0, hj,  hr,  hi],
        [hj,  1.0, jr,  ji],
        [hr,  jr,  1.0, ri],
        [hi,  ji,  ri,  1.0],
    ]


# ================================================================== 결정론


@dataclass
class Scenario:
    name: str
    label: str
    house_growth: float
    jeonse_growth: float
    rate_delta: float
    income_growth_delta: float
    living_cost_delta: float = 0.0
    deposit_delay_months: int = 0
    deposit_recovery_ratio: float = 1.0
    narrative: str = ""


def deterministic_scenarios(a: Assumptions) -> list[Scenario]:
    """설명용 시나리오. 사람이 이해할 수 있는 이야기여야 한다."""
    return [
        Scenario("BASE", "기준", a.house_price_growth, a.jeonse_price_growth,
                 0.0, 0.0, narrative="현재 가정 그대로"),
        Scenario("UP", "집값 상승", a.house_price_growth + 0.06,
                 a.jeonse_price_growth + 0.04, 0.0, 0.0,
                 narrative="매매 강세, 전세도 동반 상승. 금리 유지"),
        Scenario("FLAT", "횡보", 0.0, a.jeonse_price_growth * 0.5, 0.0, 0.0,
                 narrative="매매 정체, 전세 완만"),
        Scenario("STRESS", "복합 스트레스", a.house_price_growth - 0.09,
                 a.jeonse_price_growth - 0.05, 0.020, -0.03,
                 living_cost_delta=0.01,
                 narrative=("금리 +2%p, 집값 하락, 소득 둔화가 동시에 발생. "
                            "이 셋은 따로 오지 않는다.")),
        Scenario("DEPOSIT_DELAY", "보증금 반환지연", a.house_price_growth,
                 a.jeonse_price_growth - 0.05, 0.005, 0.0,
                 deposit_delay_months=6,
                 narrative=("역전세로 만기에 보증금이 6개월 지연. 초안이 통째로 "
                            "빠뜨린 시나리오이고, 전세 가구의 실제 최대 사고다.")),
        Scenario("DEPOSIT_LOSS", "보증금 일부 손실", a.house_price_growth,
                 a.jeonse_price_growth - 0.08, 0.005, 0.0,
                 deposit_delay_months=12, deposit_recovery_ratio=0.80,
                 narrative="반환보증 미가입 + 선순위 채권 존재 시의 최악 경로"),
        Scenario("INCOME_UP", "소득 증가", a.house_price_growth,
                 a.jeonse_price_growth, 0.0, 0.03,
                 narrative="승진/이직으로 가구소득 +3%p"),
        Scenario("SPEND_UP", "가족 지출 증가", a.house_price_growth,
                 a.jeonse_price_growth, 0.0, 0.0, living_cost_delta=0.03,
                 narrative="둘째 + 사교육 + 차량으로 생활비 +3%p"),
    ]


def scenario_path(sc: Scenario, a: Assumptions, horizon: int) -> Path:
    n = horizon + 1
    house = [(1.0 + sc.house_growth) ** (t / 12.0) for t in range(n)]
    jeonse = [(1.0 + sc.jeonse_growth) ** (t / 12.0) for t in range(n)]
    rate = [sc.rate_delta] * n
    income = [(1.0 + sc.income_growth_delta) ** (t / 12.0) for t in range(n)]
    pm = (1.0 + a.portfolio_return) ** (1 / 12.0) - 1.0
    port = [pm] * n
    return Path(house, jeonse, rate, income, port)


# ================================================================== 몬테카를로


def random_path(
    a: Assumptions, horizon: int, rng: random.Random, L: list[list[float]]
) -> Path:
    """상관구조를 가진 무작위 경로. 금리↑와 가격↓가 함께 오도록."""
    n = horizon + 1
    dt = 1.0 / 12.0
    sq = math.sqrt(dt)

    house, jeonse, rate, income, port = [1.0], [1.0], [0.0], [1.0], [0.0]
    h, j, inc = 1.0, 1.0, 1.0
    r = 0.0
    pm = (1.0 + a.portfolio_return) ** dt - 1.0
    pv = a.portfolio_volatility * sq

    for _ in range(1, n):
        z = [rng.gauss(0, 1) for _ in range(4)]
        e = _correlate(L, z)

        h *= math.exp((a.house_price_growth - 0.5 * a.house_price_volatility**2) * dt
                      + a.house_price_volatility * sq * e[0])
        j *= math.exp((a.jeonse_price_growth - 0.5 * a.jeonse_price_volatility**2) * dt
                      + a.jeonse_price_volatility * sq * e[1])
        r = r * 0.98 + a.rate_volatility * sq * e[2]      # 평균회귀
        inc *= math.exp((a.income_growth - 0.5 * 0.02**2) * dt + 0.02 * sq * e[3])

        house.append(h)
        jeonse.append(j)
        rate.append(r)
        income.append(inc)
        port.append(pm + pv * (0.3 * e[0] + 0.954 * rng.gauss(0, 1)))

    return Path(house, jeonse, rate, income, port)


@dataclass
class OptionRisk:
    name: str
    n: int
    p10: float
    p50: float
    p90: float
    mean: float
    cvar05: float                     # 하위 5% 평균 - 꼬리 위험
    prob_liquidity_breach: float
    prob_forced_move: float
    prob_infeasible: float
    worst: float
    samples: list[float] = field(default_factory=list)

    def passes(self, max_breach: float, max_forced: float) -> bool:
        return (
            self.prob_liquidity_breach <= max_breach
            and self.prob_forced_move <= max_forced
            and self.prob_infeasible <= 0.001
        )


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def monte_carlo(
    state: FamilyState,
    policy: PolicySet,
    n_paths: int = 300,
    seed: int = 20260905,
    horizon: int | None = None,
) -> dict[str, OptionRisk]:
    """상관 몬테카를로. 보증금 반환지연도 확률적으로 샘플링한다."""
    from fde.budget import build_living_cost_path
    from fde.decision import enumerate_options
    from fde.options import BuildContext, build
    from fde.simulate import simulate

    H = horizon or state.assumptions.horizon_months
    a = state.assumptions
    L = cholesky(correlation_matrix(a))
    rng = random.Random(seed)

    living = build_living_cost_path(state, policy, H)
    specs = enumerate_options(state)
    T = max(0, min(state.months_to_expiry(), H - 1))
    risk = assess_deposit_risk(state.housing, policy)

    acc: dict[str, dict] = {
        s.name: {"nw": [], "breach": 0, "forced": 0, "infeasible": 0} for s in specs
    }

    for _ in range(n_paths):
        path = random_path(a, H, rng, L)

        # 보증금 반환 지연/손실 샘플링 - A-1 리스크가 실제로 물리는 지점
        if rng.random() < risk.prob_delay:
            delay = max(1, int(rng.gauss(risk.expected_delay_months,
                                         risk.expected_delay_months * 0.4)))
            recovery = (
                1.0 - risk.expected_loss_ratio
                if rng.random() < risk.prob_partial_loss else 1.0
            )
        else:
            delay, recovery = 0, 1.0

        ctx = BuildContext(state, policy, path, T, H, T + delay, recovery)
        for spec in specs:
            sch = build(ctx, spec)
            sim = simulate(state, policy, sch, path, living, H)
            slot = acc[spec.name]
            if not sim.feasible:
                slot["infeasible"] += 1
                continue
            slot["nw"].append(sim.terminal_net_worth)
            if sim.liquidity_breach_months > 0:
                slot["breach"] += 1
            if sim.went_negative:
                slot["forced"] += 1

    out: dict[str, OptionRisk] = {}
    for name, slot in acc.items():
        nw = slot["nw"]
        if not nw:
            nan = float("nan")
            out[name] = OptionRisk(name, 0, nan, nan, nan, nan, nan,
                                   0.0, 0.0, 1.0, nan)
            continue
        s = sorted(nw)
        tail = s[: max(1, len(s) // 20)]
        out[name] = OptionRisk(
            name=name, n=len(nw),
            p10=_percentile(nw, 0.10), p50=_percentile(nw, 0.50),
            p90=_percentile(nw, 0.90), mean=sum(nw) / len(nw),
            cvar05=sum(tail) / len(tail),
            prob_liquidity_breach=slot["breach"] / n_paths,
            prob_forced_move=slot["forced"] / n_paths,
            prob_infeasible=slot["infeasible"] / n_paths,
            worst=s[0], samples=nw,
        )
    return out
