# 상장폐지 종목 데이터 — 확보 경로와 처리법

이 문서는 13부 전략의 **전제조건**을 다룬다. 생존편향이 남은 데이터로는
어떤 검증도 의미가 없으므로, 데이터 확보가 사실상 첫 번째 작업이다.

---

## 1. 왜 이것이 선택이 아니라 필수인가

| 사실 | 수치 | 출처 |
|---|---|---|
| CRSP 1926–2016 미국 주식 총수 | 25,967개 | Bessembinder (2018, JFE) |
| 그중 **상장폐지된 종목** | **9,187개 (35.4%)** | 〃 |
| 폐지 종목의 생애 매수보유수익 **중앙값** | **−91.95%** | 〃 |
| 시장 순부(純富) 전부를 만든 종목 비율 | 상위 4.3% | 〃 |
| NYSE/AMEX 연간 실적사유 폐지율 | 1.2%/년 | Shumway & Warther (1999, JF) |
| Nasdaq 연간 실적사유 폐지율 | **5.6%/년** | 〃 |

**10년 전 거래되던 미국 종목의 상당수가 오늘의 종목 리스트에 없다.**
"현재 상장 종목의 과거 주가"만 받으면 그 소멸분이 통째로 빠진다.

13부 전략은 **약세 종목을 숏**한다. 폐지되는 종목은 대부분 숏 다리에 들어간다.
따라서 생존자만 담긴 데이터는 **숏 다리의 최대 수익원을 제거**한다.
방향은 전략마다 다르지만 **크기는 항상 결론을 뒤집을 만큼 크다.**

---

## 2. 데이터 소스 (2026년 9월 기준)

### 한국 — 무료, 지금 바로 가능

**FinanceDataReader + KRX.** 상장폐지 종목의 전체 가격 이력을 무료로 준다.

```python
import FinanceDataReader as fdr
dl = fdr.StockListing('KRX-DELISTING')      # Symbol, Name, DelistingDate, Reason
px = fdr.DataReader('036360', exchange='KRX-DELISTING')   # 상장~폐지일 OHLCV
```

2020년 2월 기준 1,539개 폐지 종목이 수록돼 있었다. 사유(Reason)가 한글 원문으로
들어오므로 합병/자진폐지/실적사유를 구분해 폐지수익을 다르게 줄 수 있다 — 이게
중요하다(§4).

주의: KRX 정보데이터시스템은 2025-12-27부터 회원제 **KRX Data Marketplace**로
전면 개편됐다. 라이브러리가 붙지 못하면 [openapi.krx.co.kr](https://openapi.krx.co.kr/)
의 공식 OPEN API 또는 [공공데이터포털의 KRX상장종목정보](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15094775)로 우회한다.

리포에 수집 스크립트를 넣어 두었다: `strategy/fetch_krx.py`

```bash
pip install finance-datareader
python3 fetch_krx.py --reason-report          # 사유 매핑부터 눈으로 확인
python3 fetch_krx.py --out-dir data --start 2010-01-01
python3 run.py audit --csv data/prices.csv --delistings data/delistings.csv
```

### 미국 — 유료 구간

| 소스 | 폐지 커버리지 | 비용 | 비고 |
|---|---|---|---|
| **CRSP** (WRDS 경유) | 1926~, 사실상 표준. 폐지수익 코드까지 제공 | 기관·대학 라이선스 | 학생/연구자면 소속 기관 WRDS 먼저 확인 |
| **Norgate Data** | 1950~ 폐지 25,222종목, 과거 지수 구성종목 포함 | Diamond 연 **USD 787.50** (Platinum 이상에서 폐지 포함) | 개인 퀀트가 가장 많이 쓰는 구간 |
| **Sharadar** (Nasdaq Data Link) | 32,000+ 활성/폐지 티커, 90년대~, point-in-time | 데이터셋별 구매, 무료 티어는 DJIA 30종목만 | SF1/TICKERS 에 폐지·파산·피인수 메타데이터 포함 |
| **EODHD** | `delisted=1` 플래그로 거래소별 폐지 심볼, 폐지일까지 전체 이력 | All-World **USD 19.99/월**~ | 미국 26,000+ / 비미국 42,000+ 티커 |
| Bloomberg / LSEG / FactSet | 완비 | 기관가 | 이미 단말이 있으면 그것부터 |

```
GET https://eodhd.com/api/exchange-symbol-list/US?api_token=...&delisted=1
```

### 쓰면 안 되는 것

**yfinance / 대부분의 무료 API로 "현재 상장 종목 리스트"를 받아 과거를 조회하는 방식.**
폐지 티커는 조회 자체가 안 되거나 빈 값이 온다. 이것이 개인 백테스트에서
생존편향이 들어오는 가장 흔한 경로다.

### 암호화폐

7부에서 다룬 알트코인은 **주식보다 소멸률이 훨씬 높다.**
거래소 상장폐지·러그풀·체인 사망을 포함하려면 CoinGecko/CoinMarketCap의
inactive/delisted 목록을 별도로 받아야 한다. 현재 상장 코인만으로 백테스트하면
가장 심한 형태의 생존편향이 된다.

---

## 3. 데이터를 구해도 남는 함정 — 폐지 손익이 조용히 사라진다

가격 패널만 준비하면 폐지일 이후 그 종목 열이 `NaN`이 된다.
pandas 합산은 `NaN`을 0으로 취급하므로, **보유 중이던 포지션이 손익 없이 증발한다.**
즉 폐지 종목을 데이터에 넣어도 폐지 손익은 여전히 빠진다.

`strategy/universe.py` 가 이 구멍을 막는다 — 마지막 유효봉의 **다음 봉**에
폐지수익 1기를 명시적으로 주입한다. 다음 봉인 이유는 그 시점의 보유비중이
`w.shift(1)`로 직전 봉에서 결정된 것, 곧 "폐지를 맞은 포지션"이기 때문이다.

---

## 4. 폐지수익을 얼마로 놓을 것인가

사유별로 다르다. 합병으로 사라진 종목에 −100%를 주면 그냥 틀린 데이터다.

| 사유 | 적용값 | 근거 |
|---|---|---|
| 파산·청산 | −100% | 주식 소각 |
| 실적사유 (NYSE/AMEX) | **−30%** | Shumway (1997, JF), 1962–93 평균 −29.9% |
| 실적사유 (Nasdaq) | **−55%** | Shumway & Warther (1999, JF) |
| 합병·피인수·자진폐지 | 0% | 대가 수령으로 근사 |
| 시장 이전 | 0% | 실질 폐지 아님 |
| 불명 | −55% | 보수적 기본값 |

Shumway는 1962년 이후 부정적 사유 폐지의 **약 90%에서 실제 폐지수익이 결측**임을
보고했다. 즉 "데이터에 없으니 뺀다"가 곧 편향이다.

### 어느 쪽이 보수적인가는 전략마다 뒤집힌다

13부 전략은 약세 종목을 숏하므로 **폐지수익을 더 음수로 놓을수록 성과가 좋아진다.**
따라서 이 전략의 보수적 검증은 −100%가 아니라 **0% 쪽**이다.
한 값을 고르지 말고 양 극단을 다 돌려 범위를 보고할 것:

```bash
python3 run.py delist-sens
```

측정 결과(합성 엣지 데이터, 폐지 16건, 10년):

| 가정 | 연수익 | 샤프 | MDD |
|---|---:|---:|---:|
| 주입 없음 (조용히 소멸 — 흔한 오류) | +4.03% | +0.41 | −34.0% |
| 0% (합병·현금청산 근사, 가장 불리) | +4.03% | +0.41 | −34.0% |
| −30% (Shumway 1997) | +4.95% | +0.49 | −31.2% |
| −55% (Shumway-Warther 1999) | +5.70% | +0.56 | −28.8% |
| −100% (전액 손실) | +7.08% | +0.64 | −27.6% |
| 사유별 가정 (기본) | +4.50% | +0.45 | −34.0% |

**연수익 3.05%p, 샤프 0.23이 전략이 아니라 데이터 가정 하나에서 나온다.**
그 폭이 결론을 뒤집는다면 그 결론은 전략의 산물이 아니다.

읽어둘 것 하나 — "주입 없음"과 "0%"가 정확히 같다. 즉 **폐지 손익을 빠뜨리는 흔한
오류는 "모든 폐지가 마지막 가격에 현금 청산됐다"고 가정하는 것과 동치**다.
숏 전략에서는 이게 불리한 쪽이라 우연히 안전하지만, **롱 온리 전략에서는 정확히
반대로 대형 과대평가**가 된다.

또 하나 — 한국 시장은 **정리매매**가 있어 폐지 직전 급락이 이미 가격에 찍힌다.
그 경우 다시 −100%를 주면 이중계상이다. `fetch_krx.py` 의 주석 참조.

---

## 5. 감사 절차 — 백테스트 전에 반드시

```bash
python3 run.py audit --csv prices.csv --delistings delistings.csv
```

핵심 지표는 **연간 소멸률**이다. 실증 기준치는 NYSE/AMEX 1.2%, Nasdaq 5.6%(실적사유
한정, 합병까지 포함하면 더 높다). 받은 데이터가 **0%**로 나오면 그 패널은
생존자만 담고 있다는 뜻이고, 그 위에서 나온 성과는 전부 무효다.

그래서 `backtest.run()`은 소멸 종목이 0개인 패널에 대해 **예외를 던지고 멈춘다**
(`cfg.require_delisting_data=True`가 기본). 명시적으로 끄지 않으면 실수로
편향된 백테스트를 돌릴 수 없게 만들었다.

---

## 출처

- Bessembinder, H. (2018). "Do Stocks Outperform Treasury Bills?" *JFE* 129(3), 440–457. — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2900447) · [ASU](https://wpcarey.asu.edu/department-finance/faculty-research/do-stocks-outperform-treasury-bills)
- Shumway, T. (1997). "The Delisting Bias in CRSP Data." *Journal of Finance* 52(1), 327–340. — [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1997.tb03818.x)
- Shumway, T. & Warther, V. (1999). "The Delisting Bias in CRSP's Nasdaq Data and Its Implications for the Size Effect." *Journal of Finance*. — [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00192)
- [Norgate Data — Stock Market Packages](https://norgatedata.com/stockmarketpackages.php)
- [Sharadar](https://sharadar.com/) · [Nasdaq Data Link](https://data.nasdaq.com/databases/ZEP/documentation)
- [EODHD — Delisted Stock Companies Data](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)
- [FinanceDataReader — KRX-DELISTING](https://github.com/FinanceData/FinanceDataReader/wiki/Release-Note-0.9.1)
- [KRX Data Marketplace](https://data.krx.co.kr/) · [KRX OPEN API](https://openapi.krx.co.kr/)
