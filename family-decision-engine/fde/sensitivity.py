"""임계값 solver - 이 시스템의 핵심 산출물.

**예측을 버리고 임계값으로 바꾼다.**

초안의 시나리오 엔진은 "전세가가 몇 % 오를까?"를 묻는다. 이건 답할 수 없는
질문이고, 답한 척하면 정밀도의 환상(illusion of precision)이 된다.
소수점까지 나온 숫자는 그 자체로 설득력을 갖는데, 입력이 추측이면 출력도 추측이다.

바꿔야 할 질문:
  "전세가가 **몇 % 이상 오르면** 매수가 유리해지는가?"

이건 예측 없이 계산 가능하고, 검증 가능하고, 반증 가능하다. 그리고 월 1회
5분이면 임계값을 넘었는지 확인된다. 데일리 콜렉터도 트리거 엔진도 필요 없다.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable

from fde.budget import build_living_cost_path
from fde.decision import DecisionResult, run_decision
from fde.models import FamilyState
from fde.policy import PolicySet


# ================================================================== 파라미터


@dataclass
class Knob:
    """흔들어 볼 가정 하나."""

    key: str
    label: str
    lo: float
    hi: float
    unit: str = "pct"          # pct | krw | ratio
    plausible_lo: float | None = None
    plausible_hi: float | None = None
    note: str = ""

    def apply(self, state: FamilyState, value: float) -> FamilyState:
        a = dataclasses.replace(state.assumptions, **{self.key: value})
        return dataclasses.replace(state, assumptions=a)

    def current(self, state: FamilyState) -> float:
        return getattr(state.assumptions, self.key)

    def fmt(self, v: float) -> str:
        if self.unit == "pct":
            return f"{v * 100:.2f}%"
        if self.unit == "krw":
            from fde.money import fmt_krw
            return fmt_krw(v)
        return f"{v:.3f}"


DEFAULT_KNOBS = [
    Knob("jeonse_price_growth", "전세보증금 상승률(연)", -0.05, 0.15,
         plausible_lo=-0.02, plausible_hi=0.08,
         note="전세 옵션의 비용을 직접 결정. 가장 자주 결론을 뒤집는 변수."),
    Knob("house_price_growth", "주택가격 상승률(연)", -0.08, 0.12,
         plausible_lo=-0.03, plausible_hi=0.06,
         note="예측하지 말 것. 임계값만 보고 넘었는지 확인할 것."),
    Knob("mortgage_rate", "주담대 금리(연)", 0.020, 0.080,
         plausible_lo=0.030, plausible_hi=0.060,
         note="매수 옵션의 이자비용."),
    Knob("jeonse_loan_rate", "전세대출 금리(연)", 0.015, 0.070,
         plausible_lo=0.025, plausible_hi=0.050),
    Knob("portfolio_return", "투자 기대수익률(연)", 0.00, 0.12,
         plausible_lo=0.02, plausible_hi=0.08,
         note="현금을 쥐는 옵션(전세/월세)의 기회비용. 과대 설정 주의."),
    Knob("income_growth", "소득 증가율(연)", -0.02, 0.10,
         plausible_lo=0.00, plausible_hi=0.06),
    Knob("living_cost_growth", "생활비 증가율(연)", 0.00, 0.08,
         plausible_lo=0.01, plausible_hi=0.05,
         note="육아비 계단과 곱해져 저축률을 좌우."),
]


# ================================================================== solver


@dataclass
class Threshold:
    knob: Knob
    current_value: float
    crossing: float | None
    direction: str                 # "increase" | "decrease" | None
    winner_before: str
    winner_after: str
    within_plausible: bool
    distance_pct: float            # 현재값에서 임계까지 상대 거리
    note: str = ""

    def render(self) -> str:
        if self.crossing is None:
            return (
                f"{self.knob.label}: 검토 범위"
                f"[{self.knob.fmt(self.knob.lo)}~{self.knob.fmt(self.knob.hi)}]"
                f" 안에서 결론이 바뀌지 않음 (현재 {self.knob.fmt(self.current_value)})"
            )
        arrow = "이상" if self.direction == "increase" else "이하"
        flag = "  ← 현실적 범위 안!" if self.within_plausible else ""
        return (
            f"{self.knob.label}이 {self.knob.fmt(self.crossing)} {arrow}이면 "
            f"'{self.winner_before}' → '{self.winner_after}' 로 뒤집힘 "
            f"(현재 {self.knob.fmt(self.current_value)}){flag}"
        )


@dataclass
class SensitivityReport:
    baseline_winner: str
    baseline_margin: float
    thresholds: list[Threshold]
    fragile: list[Threshold] = field(default_factory=list)
    robust: bool = False
    summary: str = ""


def _winner_of(state: FamilyState, policy: PolicySet, cache_living=None) -> tuple[str, float]:
    r = run_decision(state, policy, living=cache_living)
    b = r.best
    return (b.spec.name if b else "(전 옵션 탈락)", r.margin)


def find_threshold(
    state: FamilyState,
    policy: PolicySet,
    knob: Knob,
    baseline_winner: str,
    grid: int = 14,
    tol: float = 1e-4,
    max_bisect: int = 24,
) -> Threshold:
    """knob 을 흔들어 1위가 바뀌는 지점을 찾는다.

    격자 스캔으로 부호 변화를 찾고 그 구간만 이분법으로 좁힌다.
    (승자 함수는 단조가 아닐 수 있으므로 이분법만 쓰면 안 된다.)
    """
    cur = knob.current(state)
    living = build_living_cost_path(state, policy, state.assumptions.horizon_months)

    def winner_at(v: float) -> str:
        st = knob.apply(state, v)
        lv = (
            build_living_cost_path(st, policy, st.assumptions.horizon_months)
            if knob.key == "living_cost_growth"
            else living
        )
        return _winner_of(st, policy, lv)[0]

    xs = [knob.lo + (knob.hi - knob.lo) * i / (grid - 1) for i in range(grid)]
    if cur not in xs:
        xs.append(cur)
        xs.sort()
    winners = [winner_at(x) for x in xs]

    # 현재값 위치에서 좌우로 가장 가까운 변화 지점
    try:
        cur_idx = xs.index(cur)
    except ValueError:
        cur_idx = min(range(len(xs)), key=lambda i: abs(xs[i] - cur))

    best: tuple[float, str, str] | None = None
    best_dist = float("inf")
    for i in range(len(xs) - 1):
        if winners[i] == winners[i + 1]:
            continue
        lo, hi = xs[i], xs[i + 1]
        wlo, whi = winners[i], winners[i + 1]
        for _ in range(max_bisect):
            if hi - lo < tol:
                break
            mid = (lo + hi) / 2
            if winner_at(mid) == wlo:
                lo = mid
            else:
                hi = mid
        crossing = (lo + hi) / 2
        d = abs(crossing - cur)
        if d < best_dist:
            best_dist = d
            before, after = (wlo, whi) if crossing >= cur else (whi, wlo)
            best = (crossing, before, after)

    if best is None:
        return Threshold(knob, cur, None, None, baseline_winner, baseline_winner,
                         False, float("inf"))

    crossing, before, after = best
    direction = "increase" if crossing > cur else "decrease"
    plo = knob.plausible_lo if knob.plausible_lo is not None else knob.lo
    phi = knob.plausible_hi if knob.plausible_hi is not None else knob.hi
    within = plo <= crossing <= phi
    dist = abs(crossing - cur) / max(1e-9, abs(phi - plo))

    return Threshold(knob, cur, crossing, direction, baseline_winner, after,
                     within, dist, knob.note)


def run_sensitivity(
    state: FamilyState,
    policy: PolicySet,
    knobs: list[Knob] | None = None,
    grid: int = 14,
) -> SensitivityReport:
    knobs = knobs or DEFAULT_KNOBS
    winner, margin = _winner_of(state, policy)

    ths = [find_threshold(state, policy, k, winner, grid=grid) for k in knobs]
    ths.sort(key=lambda t: (t.crossing is None, t.distance_pct))

    fragile = [t for t in ths if t.crossing is not None and t.within_plausible]
    robust = not fragile

    if robust:
        summary = (
            f"'{winner}' 결론은 검토한 {len(knobs)}개 가정을 현실적 범위 안에서 "
            f"흔들어도 유지됩니다. 비교적 견고한 결론입니다."
        )
    else:
        top = fragile[0]
        summary = (
            f"'{winner}' 결론은 견고하지 않습니다. "
            f"특히 {top.knob.label} 가정에 의존하며, "
            f"{top.knob.fmt(top.crossing)} "
            f"{'이상' if top.direction == 'increase' else '이하'}이면 뒤집힙니다."
        )

    return SensitivityReport(winner, margin, ths, fragile, robust, summary)


# ================================================================== 후보 가격 임계


def price_threshold_for_buy(
    state: FamilyState,
    policy: PolicySet,
    candidate_index: int,
    lo_ratio: float = 0.6,
    hi_ratio: float = 1.3,
    steps: int = 20,
) -> tuple[float | None, str]:
    """'이 집을 얼마 이하면 사는 게 맞는가'.

    부동산에 들고 갈 수 있는 유일하게 실용적인 숫자다.
    """
    base = state.candidates[candidate_index]
    base_price = base.price_buy
    if base_price <= 0:
        return None, "매매 시세가 없습니다."

    buy_name_prefix = f"D. 매수({base.name})"
    found: float | None = None

    for i in range(steps + 1):
        ratio = hi_ratio + (lo_ratio - hi_ratio) * i / steps
        price = base_price * ratio
        cands = list(state.candidates)
        cands[candidate_index] = dataclasses.replace(base, price_buy=price)
        st = dataclasses.replace(state, candidates=cands)
        r = run_decision(st, policy)
        if r.best and r.best.spec.name.startswith(buy_name_prefix):
            found = price
            break

    if found is None:
        return None, (
            f"{base.name}: 시세의 {lo_ratio:.0%}~{hi_ratio:.0%} 구간 어디에서도 "
            f"매수가 1위가 되지 않습니다."
        )
    return found, (
        f"{base.name}: 매매가가 약 {found:,.0f}원 이하(현재 시세의 "
        f"{found / base_price:.0%})면 매수가 최선이 됩니다."
    )
