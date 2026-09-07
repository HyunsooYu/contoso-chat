# -*- coding: utf-8 -*-
"""
생존편향 처리 — 상장폐지 종목을 데이터에 넣고, 폐지 시점 손실을 손익에 반영한다.

왜 별도 모듈인가:
  가격 패널만으로는 부족하다. 폐지 종목을 CSV에 넣어도 폐지일 이후 열이 NaN 이 되고,
  NaN 은 pandas 합산에서 0 으로 취급되므로 '보유하던 포지션이 아무 일 없이 사라지는'
  결과가 된다. 즉 데이터를 제대로 구해도 폐지 손익은 여전히 누락된다.
  이 모듈은 폐지 시점에 마지막 수익 1기를 명시적으로 주입해 그 구멍을 막는다.

폐지수익 가정의 출처:
  Shumway (1997, JF)          NYSE/AMEX 실적사유 폐지, 결측 시 -30% 대입 (1962-93 평균 -29.9%)
  Shumway & Warther (1999, JF) Nasdaq 실적사유 폐지, 결측 시 -55% 대입
  Bessembinder (2018, JFE)     폐지 9,187종목의 생애 매수보유수익 중앙값 -91.95%

주의 — 어느 쪽이 '보수적'인가는 다리(leg)에 따라 뒤집힌다:
  이 전략은 약세 종목을 숏한다. 폐지되는 종목은 대개 숏 다리에 있다.
  따라서 폐지수익을 더 음수로 놓을수록 전략 성과가 '좋아진다'.
  보수적 검증은 -100% 가 아니라 0% 쪽이다. 그래서 한 값을 고르지 않고
  sensitivity() 로 양 극단을 모두 돌려 범위를 보고한다.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# 사유별 폐지수익 가정. 사유를 모르면 'unknown'.
ASSUMPTIONS = {
    "bankruptcy":   -1.00,   # 파산·청산 — 주식 소각
    "liquidation":  -1.00,
    "performance":  -0.55,   # 실적/관리종목 사유 (Shumway & Warther 1999, Nasdaq)
    "performance_nyse_amex": -0.30,   # Shumway 1997
    "merger":        0.00,   # 합병·피인수 — 대가 수령으로 근사
    "acquisition":   0.00,
    "going_private": 0.00,   # 자진상폐·공개매수
    "exchange_move": 0.00,   # 시장 이전 (실질 폐지 아님)
    "unknown":      -0.55,
}

# 감사용 실증 기준치(연간 실적사유 폐지율)
HAZARD_BENCHMARK = {
    "NYSE/AMEX (Shumway & Warther 1999)": 0.012,
    "Nasdaq (Shumway & Warther 1999)":    0.056,
}


def load_delistings(path: str) -> pd.DataFrame:
    """CSV: symbol,delist_date,reason[,delist_return]
    delist_return 이 있으면 그 값을 우선 쓰고, 없으면 reason 으로 가정값을 채운다."""
    df = pd.read_csv(path, parse_dates=["delist_date"])
    if "reason" not in df:
        df["reason"] = "unknown"
    df["reason"] = df["reason"].fillna("unknown").astype(str).str.strip().str.lower()
    if "delist_return" not in df:
        df["delist_return"] = np.nan
    return df[["symbol", "delist_date", "reason", "delist_return"]]


def resolve_returns(delistings: pd.DataFrame,
                    assumptions: dict | None = None,
                    override: float | None = None) -> pd.Series:
    """심볼 -> 적용할 폐지수익. override 를 주면 실측치까지 전부 그 값으로 덮는다
    (민감도 분석용)."""
    a = dict(ASSUMPTIONS if assumptions is None else assumptions)
    if override is not None:
        return pd.Series(override, index=delistings["symbol"].values)
    mapped = delistings["reason"].map(a).fillna(a.get("unknown", -0.55))
    r = delistings["delist_return"].astype(float).fillna(mapped)
    return pd.Series(r.values, index=delistings["symbol"].values)


def delisting_return_frame(close: pd.DataFrame, delistings: pd.DataFrame,
                           assumptions: dict | None = None,
                           override: float | None = None) -> pd.DataFrame:
    """폐지 시점(마지막 유효봉의 다음 봉)에 폐지수익 1기를 주입한 수익 프레임.

    다음 봉에 넣는 이유: 그 시점의 보유비중은 w.shift(1) 로 직전 봉에서 결정된 것이고,
    그것이 곧 '폐지를 맞은 포지션'이다. 마지막 유효봉에 넣으면 정상 수익과 겹친다.
    """
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    rets = resolve_returns(delistings, assumptions, override)
    for sym, r in rets.items():
        if sym not in close.columns:
            continue
        col = close[sym]
        if not col.notna().any():
            continue
        i = col.index.get_loc(col.last_valid_index())
        j = min(i + 1, len(close.index) - 1)
        out.iloc[j, out.columns.get_loc(sym)] = float(r)
    return out


def audit(close: pd.DataFrame, delistings: pd.DataFrame | None = None) -> dict:
    """패널이 생존편향에 오염됐는지 진단한다.

    핵심 지표는 '연간 소멸률' — 마지막 시점까지 살아남지 못한 심볼의 연율.
    0 이면 패널은 생존자만 담고 있다는 뜻이고, 이 경우 결과는 전부 무효다.
    """
    n_total = int(close.notna().any().sum())
    alive = close.iloc[-1].notna()
    n_alive = int(alive.sum())
    n_dead = n_total - n_alive
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-9)
    hazard = (n_dead / n_total / years) if n_total else 0.0
    listed_declared = 0 if delistings is None else int(
        delistings["symbol"].isin(close.columns).sum())
    return dict(n_total=n_total, n_alive=n_alive, n_dead=n_dead, years=years,
                hazard=hazard, declared=listed_declared,
                biased=(n_dead == 0),
                covered=(listed_declared >= n_dead) if n_dead else True)


def audit_report(a: dict) -> str:
    L = ["=" * 74, "생존편향 감사", "=" * 74,
         f"  심볼 {a['n_total']}개   기간 {a['years']:.1f}년",
         f"  마지막 시점 생존 {a['n_alive']}개 / 중도 소멸 {a['n_dead']}개",
         f"  연간 소멸률 {a['hazard']:.2%}",
         "  실증 기준: " + "  ".join(f"{k.split(' (')[0]} {v:.1%}"
                                    for k, v in HAZARD_BENCHMARK.items()),
         f"  폐지수익이 선언된 심볼 {a['declared']}개"]
    if a["biased"]:
        L += ["", "  [실패] 중도 소멸 종목이 0개다. 이 패널은 생존자만 담고 있다.",
              "         이 데이터로 낸 성과는 전부 과대평가다 — 백테스트를 돌리지 말 것."]
    elif not a["covered"]:
        L += ["", f"  [경고] 소멸 {a['n_dead']}개 중 {a['declared']}개만 폐지수익이 선언됐다.",
              "         나머지는 '조용히 사라진' 포지션으로 손익에서 누락된다."]
    else:
        L += ["", "  [통과] 소멸 종목이 존재하고 폐지수익이 선언되어 있다."]
    return "\n".join(L)
