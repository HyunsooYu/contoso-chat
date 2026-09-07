# -*- coding: utf-8 -*-
"""
KRX 생존편향 없는 패널 수집기 — 상장 종목 + 상장폐지 종목을 함께 받아
backtest 가 요구하는 두 파일을 만든다.

  python3 fetch_krx.py --out-dir data/ --start 2010-01-01

산출물
  prices.csv      date,symbol,close      (상장 + 폐지 종목 전부)
  delistings.csv  symbol,delist_date,reason,delist_return

의존성: pip install finance-datareader   (KRX 데이터는 무료)

주의 1 — 이 스크립트는 data.krx.co.kr 로 직접 나간다. 사내/샌드박스 프록시에서
        차단될 수 있다. 그 경우 로컬에서 실행한 뒤 CSV만 옮길 것.
주의 2 — FinanceDataReader 의 KRX-DELISTING 목록은 사유(Reason)를 한글 원문으로 준다.
        아래 REASON_MAP 이 그것을 universe.ASSUMPTIONS 의 키로 번역한다.
        매핑되지 않은 사유는 'unknown'(-55%)으로 떨어지므로, 실제 운용 전에
        --reason-report 로 한 번 훑어 매핑을 보강할 것.
주의 3 — 폐지 종목의 '마지막 종가'는 정리매매 종가다. 정리매매 기간의 급락이
        가격에 이미 반영돼 있으면 폐지수익을 다시 -100% 로 주면 이중계상이 된다.
        --assume-terminal 로 그 처리를 고른다(기본: 사유별 가정).
"""
from __future__ import annotations
import argparse, os, sys, time

REASON_MAP = [
    # (부분일치 키워드, universe.ASSUMPTIONS 키)
    ("합병",       "merger"),
    ("피흡수",     "merger"),
    ("포괄적주식", "merger"),
    ("주식교환",   "merger"),
    ("이전상장",   "exchange_move"),
    ("재상장",     "exchange_move"),
    ("신청",       "going_private"),   # 자진상장폐지
    ("자진",       "going_private"),
    ("파산",       "bankruptcy"),
    ("해산",       "liquidation"),
    ("청산",       "liquidation"),
    ("감사의견",   "performance"),
    ("자본잠식",   "performance"),
    ("매출액",     "performance"),
    ("사업보고서", "performance"),
    ("부도",       "bankruptcy"),
    ("회생",       "performance"),
    ("상장적격",   "performance"),
    ("관리종목",   "performance"),
]


def map_reason(text: str) -> str:
    t = str(text or "")
    for key, val in REASON_MAP:
        if key in t:
            return val
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--market", default="KRX", help="KRX / KOSPI / KOSDAQ")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--reason-report", action="store_true",
                    help="폐지 사유 원문과 매핑 결과만 출력하고 종료")
    a = ap.parse_args()

    try:
        import FinanceDataReader as fdr
        import pandas as pd
    except ImportError:
        print("pip install finance-datareader pandas", file=sys.stderr)
        return 2

    os.makedirs(a.out_dir, exist_ok=True)

    print("상장폐지 목록 조회...")
    dl = fdr.StockListing("KRX-DELISTING")
    dl.columns = [c.strip() for c in dl.columns]
    sym_c = "Symbol" if "Symbol" in dl else dl.columns[0]
    date_c = next((c for c in dl.columns if "Delisting" in c or "Date" in c), None)
    reason_c = next((c for c in dl.columns if "Reason" in c), None)
    dl["_reason"] = dl[reason_c].map(map_reason) if reason_c else "unknown"

    if a.reason_report:
        if reason_c:
            t = dl.groupby([reason_c, "_reason"]).size().sort_values(ascending=False)
            print(t.to_string())
            print(f"\n미매핑(unknown) {int((dl['_reason']=='unknown').sum())} / {len(dl)}건")
        return 0

    live = fdr.StockListing(a.market)
    live.columns = [c.strip() for c in live.columns]
    lsym = "Symbol" if "Symbol" in live else live.columns[0]

    dead_syms = dl[sym_c].astype(str).str.zfill(6).tolist()
    live_syms = live[lsym].astype(str).str.zfill(6).tolist()
    syms = [(s, True) for s in dead_syms] + [(s, False) for s in live_syms]
    if a.limit:
        syms = syms[:a.limit]
    print(f"대상 {len(syms)}종목 (폐지 {len(dead_syms)} + 상장 {len(live_syms)})")

    rows, ok, fail = [], 0, 0
    for i, (s, is_dead) in enumerate(syms, 1):
        try:
            df = (fdr.DataReader(s, exchange="KRX-DELISTING") if is_dead
                  else fdr.DataReader(s, a.start))
            if df is None or df.empty or "Close" not in df:
                fail += 1; continue
            px = df.loc[df.index >= a.start, "Close"].dropna()
            if px.empty:
                fail += 1; continue
            rows.append(pd.DataFrame({"date": px.index, "symbol": s,
                                      "close": px.to_numpy()}))
            ok += 1
        except Exception:
            fail += 1
        if i % 100 == 0:
            print(f"  {i}/{len(syms)}  성공 {ok} 실패 {fail}")
            time.sleep(0.5)          # 예의상 쉬어 간다

    if not rows:
        print("수집 실패 — 네트워크 또는 프록시 차단 여부를 확인할 것.", file=sys.stderr)
        return 1

    px_path = os.path.join(a.out_dir, "prices.csv")
    pd.concat(rows, ignore_index=True).to_csv(px_path, index=False)

    out = pd.DataFrame({
        "symbol": dl[sym_c].astype(str).str.zfill(6),
        "delist_date": pd.to_datetime(dl[date_c]) if date_c else pd.NaT,
        "reason": dl["_reason"],
        "delist_return": float("nan"),
    })
    dl_path = os.path.join(a.out_dir, "delistings.csv")
    out.to_csv(dl_path, index=False)

    print(f"\n완료: {px_path} ({ok}종목), {dl_path} ({len(out)}건)")
    print("다음:")
    print(f"  python3 run.py audit --csv {px_path} --delistings {dl_path}")
    print(f"  python3 run.py backtest --csv {px_path} --delistings {dl_path} --oos 2023-01-01")
    return 0


if __name__ == "__main__":
    sys.exit(main())
