# Market Indicator Tracker

어둠의 알상무단을 위한 지표추적자 (Market Indicator Tracker)

한국투자증권 Open API / ECOS / FRED / 야후 파이낸스로 시장 지표를 로컬에 수집하고, 구글 시트에 올릴
엑셀 파일을 만드는 도구.

## 1. 설치 / 인증

```bash
pip install -r requirements.txt
```

키는 환경변수가 우선이고, 없으면 저장소 안의 `API-KEY.txt`를 읽는다(`.gitignore` 등록됨).

```
APP Key: ...           # 한국투자증권
APP Secret: ...
ECOS Key: ...          # 한국은행 ECOS 인증키 (국고채 3년/10년 대체 경로)
```

환경변수로 넘길 경우:

```bash
export KIS_APP_KEY=... KIS_APP_SECRET=... ECOS_API_KEY=...
export KIS_ENV=prod   # 모의투자면 vps
```

접근토큰은 `~/.kis_token.json`에 캐시되며(권한 600) 만료 10분 전까지 재사용한다.
KIS는 토큰 발급을 1분에 1회로 제한하므로 캐시를 지우지 말 것.

## 2. 실행

```bash
python collect.py --daily        # 오늘치 추가 (매일)
python upload_sheets.py --data   # 구글 시트 반영
```

```bash
python collect.py --init      # 과거치 전체 수집 + market_data.xlsx 생성 (최초 1회)
python collect.py --daily     # 최근 10영업일 갱신 (매일)
python collect.py --excel     # data/*.csv -> market_data.xlsx 재생성
python import_ecos.py "시장금리(일별)_04000531.xlsx"   # ECOS 엑셀 -> data/ktb3y.csv
python test_collect.py        # 네트워크 없이 로직 검증
```

```bash
python collect.py --snapshot              # 오늘 기준 CLAUDE.md 형식 스냅샷 표
python collect.py --snapshot 2026-08-21   # 특정 날짜
```

`--daily`/`--init`은 마지막 줄에 요약을 찍는다: `21계열 갱신 · stale 0`.
계열의 마지막 데이터가 5일(달력) 넘게 낡으면 `stale`로 이름이 올라간다.
휴장은 임계 안에 들어오므로 조용하고, 소스가 깨지면 드러난다.
**전 계열이 낡았을 때만 종료 코드가 non-zero다** — 계열 하나 때문에 매일
실패로 표시하면 실패 표시 자체가 무뎌진다.

수집 결과는 `data/<지표>.csv`에 날짜 기준으로 누적된다(같은 날짜는 최신값으로 덮어씀).
종목·지수 코드는 전부 `codes/instruments.json`에 있다. 코드가 바뀌면 그 파일만 고치면 된다.

## 3. 수집 지표 / 사용 API

기간·주기는 [`collect.py`](collect.py)의 `SPEC` 한 곳에서 정한다. 수집 범위와 출력 가공(기간 자르기 +
주간 리샘플)이 모두 이 값을 따르므로 범위를 바꾸려면 `SPEC`만 고치면 된다.

| 시트 | 지표 | 출처 (TR ID) | 주기 | 기간 | 행수 |
|---|---|---|---|---|---|
| `kospi` | 코스피 OHLC | 국내주식업종기간별시세 `FHKUP03500100` | 일 | 6개월 | 122 |
| `kosdaq` | 코스닥 OHLC | 동일 (`1001`) | 일 | 6개월 | 122 |
| `samsung_elec` | 삼성전자 OHLC | 국내주식기간별시세 `FHKST03010100` | 일 | 6개월 | 122 |
| `sk_hynix` | SK하이닉스 OHLC | 동일 (`000660`) | 일 | 6개월 | 122 |
| `wti` | WTI 원유 선물 OHLC | 해외선물 `HHDFC55020100`, 실패 시 **야후 `CL=F`** | 일 | 6개월 | 126 |
| `usdkrw` | 원달러(원/달러 KMB) | 해외 기간별시세 `FHKST03030100` (X/`FX@KRW`) | 일 | 1년 | 243 |
| `usdjpy` | 달러엔(엔/달러) | 동일 (X/`FX@JPY`) | 일 | 1년 | 250 |
| `ust10y` | 미국채 10년 금리 | **FRED `DGS10`** (KIS 미지원) | 일 | 3년 | - |
| `ktb3y` | 국고채 3년 금리 | **한국은행 ECOS** `817Y002`/`010200000` | 주(금) | 3년 | 157 |
| `investor_flow` | 주체별 순매수(외국인/기관/개인/연기금/투신) | 시장별 투자자매매동향(일별) `FHPTJ04040000` | 주(금) | 2년 | 105 |
| `sp500` | S&P 500 OHLC | 야후 `^GSPC` | 일 | 6개월 | - |
| `nasdaq` | 나스닥 OHLC | 야후 `^IXIC` | 일 | 6개월 | - |
| `dow` | 다우 OHLC | 야후 `^DJI` | 일 | 6개월 | - |
| `russell2000` | 러셀 2000 OHLC | 야후 `^RUT` | 일 | 6개월 | - |
| `dxy` | 달러지수 OHLC | 야후 `DX-Y.NYB` | 일 | 6개월 | - |
| `btc` | 비트코인 OHLC | 야후 `BTC-USD` | 일 | 6개월 | - |
| `gold` | 금 선물 OHLC | 야후 `GC=F` | 일 | 6개월 | - |
| `ust2y` | 미국채 2년 금리 | FRED `DGS2` | 일 | 3년 | - |
| `ktb10y` | 국고채 10년 금리 | ECOS `817Y002`/`010210000` | 주(금) | 3년 | - |
| `oracle` | 오라클 OHLC | 야후 `ORCL` | 일 | 6개월 | - |
| `nvidia` | 엔비디아 OHLC | 야후 `NVDA` | 일 | 6개월 | - |

CSV에는 수집한 원본(일별)을 그대로 쌓고, 기간 자르기·주간 집계는 출력 시점(`for_output`)에 한다.
범위를 다시 늘려도 이미 받아둔 데이터는 버려지지 않는다.

- 주간 집계: 순매수는 **주간 합계**, 가격·금리는 **주 마지막 값**(W-FRI).
- 누적/이동평균은 저장하지 않고 출력 시 계산: `foreign_cum`, `foreign_ma4w`(주간 4행 이동평균),
  `foreign_cum_ma4w`, 각 주체별 `*_cum`. 순매수 단위는 **백만원**(`*_ntby_tr_pbmn`).

### 실계좌 프로브로 확인된 사항 (2026-08-04)

- **환율** `FX@KRW`(원/달러 KMB), `FX@JPY`(엔/달러) 정상 조회.
- **미국채 10년** — KIS에는 시계열이 없다. `FHKST03030100`에 `.TNX`, `TNX`, `^TNX`, `.IRX`,
  `.FVX`, `.TYX`, `BY0202`(해외 마스터의 "미국 10년 T-NOTE 수익률")를 시장코드 `I/N/S/X` 조합으로
  전부 시도했지만 오류 없이 빈 응답(`output2` 0건)만 온다 → **FRED `DGS10`**로 대체.
  키가 필요 없고 주간(금요일) 리샘플까지 로컬에서 처리한다.
  ECOS에도 `902Y023 주요국제금리`가 있지만 **월간**이라 주간 요구에 못 미친다.
- **국고채 3년** — KIS 장내채권 API(`FHKBJ773404C0`)는 채권 *가격*만 주고 금리를 주지 않는다.
  ECOS(`817Y002` / `010200000`)가 맞는 소스이고, 인증키로 3년치(729영업일, 2023-08-07~)를 자동
  수집한다. 값은 ECOS 다운로드 파일과 일치 확인(2024-07-23 = 3.084, 2026-08-03 = 3.742).
  키 없이 시작할 때만 `import_ecos.py`로 엑셀/CSV를 적재하면 된다.
- **WTI** — 종목코드(`CLU26` 등)는 유효하지만 시세 호출이 `EGW00551 NYMEX SUB거래소 신청 계좌가
  아닙니다`로 막힌다. 이 경우 **야후 `CL=F`(근월물 연결선물) 일봉으로 자동 대체**한다(키 불필요,
  2년 502행 OHLC 확인). KIS HTS/MTS에서 해외선물 NYMEX 시세를 신청하면 자동으로 KIS 경로를 탄다.
  근월물 코드는 `CL + 월코드 + 연도2자리`로 자동 계산하며, 고정하려면
  `codes/instruments.json`의 `futures.wti.srs_cd`에 직접 넣는다.

  WTI 소스 비교(2026-08-03 기준 실측):

  | 소스 | OHLC | 과거 | 키 | 값 |
  |---|---|---|---|---|
  | KIS 해외선물 | O | 2년+ | KIS + NYMEX 시세 신청 | 신청 전 조회 불가 |
  | **야후 `CL=F`** (현재 사용) | **O** | 2년(504행) | 불필요 | 종가 79.51 |
  | OilPriceAPI 무료 | X (현물가만) | 1년(354행, `past_year`) | 발급됨 | 79.73 |
  | FRED `DCOILWTICO` | X (종가만) | 무제한 | 불필요 | 약 1주 지연 |

  OilPriceAPI는 `past_day/week/month/year`만 있고 임의 구간(`by_period`)은 100건에서 잘리며
  시가·고가·저가가 없어 캔들 차트에는 못 쓴다. 최신가 확인용으로는 충분하다.
- **호출 제한** — 시세 API는 초당 3건 근처에서 `EGW00201`이 난다. 클라이언트가 요청 간격 0.35초 +
  재시도 3회로 처리한다.
- **업종(지수) 시세** 응답은 약 50건에서 잘려서 60일씩 끊어 호출한다(주식·환율은 100일).

### 투자자 필드 매핑(INVESTOR_MAP) 수정법

위치: [`collect.py`](collect.py)의 `INVESTOR_MAP` 딕셔너리(`fetch_investor` 바로 위).
`"출력 컬럼명": ["KIS 응답 필드 후보", ...]` 형태이고, 앞에서부터 값이 있는 첫 필드를 쓴다.

```python
INVESTOR_MAP = {
    "date": ["stck_bsop_date"],
    "foreign": ["frgn_ntby_tr_pbmn"],        # 외국인
    "institution": ["orgn_ntby_tr_pbmn"],    # 기관계
    "individual": ["prsn_ntby_tr_pbmn"],     # 개인
    "pension": ["fund_ntby_tr_pbmn"],        # 연기금등
    "trust": ["ivtr_ntby_tr_pbmn"],          # 투신
    "close": ["bstp_nmix_prpr"],
}
```

주체를 더 넣고 싶으면 한 줄 추가하면 된다. 실제 응답에 있는 필드(확인됨):

| 접두어 | 주체 | 접두어 | 주체 |
|---|---|---|---|
| `frgn_` | 외국인 | `bank_` | 은행 |
| `frgn_reg_` / `frgn_nreg_` | 등록/미등록 외국인 | `insu_` | 보험 |
| `prsn_` | 개인 | `mrbn_` | 종금·저축은행 |
| `orgn_` | 기관계 | `fund_` | 연기금등 |
| `scrt_` | 증권 | `etc_orgt_` | 기타법인·단체 |
| `ivtr_` | 투신 | `etc_corp_` | 기타법인 |
| `pe_fund_` | 사모펀드 | `etc_` | 기타계 |

접미어는 금액이 `_ntby_tr_pbmn`(백만원), 수량이 `_ntby_qty`(주). 예외적으로 사모펀드 수량은
`pe_fund_ntby_vol`, 기타법인 수량은 `etc_corp_ntby_vol`이다. 수량 기준으로 보고 싶으면
`"foreign": ["frgn_ntby_qty"]`처럼 바꾸면 된다.

필드명이 안 맞으면 실행 중 `[주의] 투자자 필드 미매핑: [...] / 응답필드: [...]`가 한 번 출력된다.

## 4. 자동 실행

**평일 16:10(KST) GitHub Actions에서 자동 실행된다** (`.github/workflows/daily.yml`).
`data/`가 이제 저장소에 커밋되므로 실행할 때마다 Actions가 결과를 다시 커밋해
푸시한다 — 이게 유일한 실행 지점이면 된다. 설정법은 8절 참고.

로컬/VPS에서 손으로 또는 cron으로 병행 실행하면 `data/` 사본이 갈리고 구글시트를
서로 덮어쓴다. 자동 실행은 Actions 한 곳으로 두고, 다른 환경은 필요할 때만 손으로
돌린다. 자체 cron이 필요하면 5절 끝의 "매일 갱신에 붙이기" 참고 (Actions와 동시에
쓰지 말 것).

## 5. 구글 시트 업로드 + 대시보드

대상 시트 ID는 `upload_sheets.py`의 `SPREADSHEET_ID` 상수에서 바꾼다.

```bash
python upload_sheets.py            # 데이터 업로드 + dashboard 재생성
python upload_sheets.py --data     # 데이터만
python upload_sheets.py --charts   # 차트만 재생성
```

### 서비스 계정 준비 (최초 1회, 약 5분)

1. https://console.cloud.google.com → 프로젝트 생성(아무 이름)
2. **API 및 서비스 → 라이브러리** → `Google Sheets API` 검색 → **사용 설정**
3. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정**
   - 이름 아무거나, 역할은 지정하지 않아도 됨 → 완료
4. 만들어진 서비스 계정 클릭 → **키 → 키 추가 → 새 키 만들기 → JSON** → 다운로드
   - 받은 파일을 이 저장소에 `google-service-account.json` 으로 저장 (`.gitignore` 등록됨)
5. 구글 시트 열기 → **공유** → JSON 안의 `client_email`
   (`...@....iam.gserviceaccount.com`) 을 **편집자**로 추가

### 만들어지는 것

- 지표별 시트: `SPEC`(collect.py)에 있는 21개 계열 전부 — `kospi`, `kosdaq`,
  `samsung_elec`, `sk_hynix`, `wti`, `usdkrw`, `usdjpy`, `ust10y`, `ust2y`,
  `ktb3y`, `ktb10y`, `investor_flow`, `sp500`, `nasdaq`, `dow`, `russell2000`,
  `dxy`, `btc`, `gold`, `oracle`, `nvidia` — 매 실행마다 전체 덮어쓰기(중복·순서
  걱정 없음)
- `dashboard` 시트(맨 앞): 760x570px(4:3) 차트, 픽셀 오프셋으로 겹치지 않게 배치.
  배치는 `upload_sheets.py`의 `LAYOUT` 리스트가 그대로 화면 순서다.

  | 행 | 내용 |
  |---|---|
  | 1 | 외국인 누적 순매수 + 4주 MA · 주체별 누적 순매수(외국인/기관/개인/연기금) |
  | 2 | KOSPI 캔들 · KOSDAQ 캔들 · 나스닥 캔들 |
  | 3 | 미국채 10년 금리 · 국고채 3년 금리 |
  | 4 | WTI 원유 선물 캔들 · 금 캔들 |
  | 5 | 삼성전자 캔들 · SK하이닉스 캔들 · 엔비디아 캔들 · 오라클 캔들 |
  | 6 | 원달러 환율 캔들 · 달러엔 환율 캔들 |

  `--charts` 실행 시 `dashboard`를 통째로 지우고 다시 만든다(차트 중복 방지).

`investor_flow` 시트에는 누적/이동평균 열(`*_cum`, `foreign_ma4w`, `foreign_cum_ma4w`)이
업로드 시점에 계산되어 함께 올라간다.

**날짜 열은 텍스트로 올린다** (`valueInputOption=RAW`). 구글 캔들차트는 도메인(1열)이 텍스트여야
해서, 날짜형으로 들어가면 차트가 `1열은 텍스트여야 합니다` 오류를 내고 그려지지 않는다.
시트에서 날짜 열 서식을 날짜로 바꾸면 같은 오류가 재발하니 그대로 두는 편이 좋다.

### 캔들차트 세로축은 손으로 한 번 넣어야 한다

Sheets API의 `candlestickChart`에는 축 설정 필드가 아예 없다(`axis` 를 넣으면 400). 그래서 API로
만든 캔들차트는 **0부터** 시작해 환율처럼 변동폭이 작은 지표가 일직선으로 보인다. 선 그래프는
`basicChart.axis.viewWindowOptions` 로 코드에서 자동 설정되므로 손댈 필요 없다.

```bash
python upload_sheets.py --ranges   # 데이터에 맞는 최솟값/최댓값 출력
```

**캔들 색상도 바꿀 수 없다.** Sheets 캔들차트는 시리즈 그룹을 1개만 허용하고
(`More than 1 candlestickChartSpec.data is not supported`) 색상 필드 자체가 없다. 상승/하락을
빨강·파랑으로 칠하려면 시트가 아니라 로컬에서 이미지(mplfinance 등)로 그려 붙이는 수밖에 없다.

출력된 값을 각 캔들차트에서 **차트 더블클릭 → 맞춤설정 → 세로축 → 최솟값/최댓값**에 입력한다.
`--charts` 로 대시보드를 재생성하면 차트가 새로 만들어지므로 이 값도 다시 넣어야 한다.
데이터만 갱신(`--data`)할 때는 유지된다 — 그래서 매일 갱신은 `--data` 를 쓴다.

### 매일 갱신에 붙이기

```cron
0 18 * * 1-5 cd /path/to/market-indicator-tracker && python3 collect.py --daily && python3 upload_sheets.py --data >> update.log 2>&1
```

`/path/to/market-indicator-tracker`는 저장소를 clone한 실제 경로로 바꾼다.
차트는 데이터 범위를 행 수까지 잡아두므로, 행이 늘면 `--charts`를 가끔(월 1회 정도) 다시 돌리면 된다.

## 6. 정적 대시보드 (GitHub Pages)

```bash
python build_dashboard.py    # data/*.csv -> docs/data.json
```

`docs/index.html`이 `docs/data.json`을 읽어 [Lightweight Charts](https://tradingview.github.io/lightweight-charts/)로
그린다. `docs/`를 GitHub Pages로 게시하면(설정 → Pages → 브랜치/`docs` 폴더)
별도 서버 없이 정적으로 뜬다.

- 위쪽 탭으로 지표를 하나씩 보거나 **통합**에서 전부 한 화면에 놓고 본다.
  선택한 탭은 URL 해시에 남아 새로고침해도 유지된다.
- 통합 뷰는 섹터(지수/종목/환율/원자재·코인/금리/수급)마다 한 행을 쓰고, 그 안의
  차트가 폭을 똑같이 나눈다 — 개수가 2개든 4개든 행의 총 폭은 같다. 섹터 순서는
  `docs/app.js`의 `SECTORS`가 정한다.
- 차트의 확대·이동은 꺼 두었다. 페이지를 스크롤하다 커서가 차트를 지나면 휠이
  확대로 먹혀서 보던 구간이 멋대로 바뀌기 때문이다. 구간은 `view`로만 정한다.
- 금리를 뺀 나머지는 캔들. 캔들에 마우스를 올리면 그 날짜의 시가·고가·저가·종가와
  이동평균 값이 뜬다.
- 보조지표는 `docs/app.js`의 `CHARTS` 한 곳에서 정한다. `ma`는 이동평균 기간들,
  `extras`는 `ichimoku`/`macd`/`rsi`(서브패널로 붙는다), `view`는 처음 보여줄 봉 수다.
  계산식은 `docs/indicators.js`에 있다.
- 그리는 계열은 텔레그램 브리핑(`notify_daily.py`의 `BRIEFING_GROUPS`)과 같다.
  `data/`에는 S&P·다우·러셀·달러지수·비트코인 등도 쌓이지만 차트로는 그리지 않는다.

`build_dashboard.py`는 기간을 자르지 않은 전체 데이터를 넘긴다
(`output_frames(trim=False)`). 이동평균·일목균형표가 앞쪽 데이터를 먹기 때문에,
`SPEC` 기간만 넘기면 화면 왼쪽에서 MA120 같은 선이 잘려 나온다.

화면에 보이는 구간(`view`)보다 **이동평균 기간만큼 앞의 데이터가 더 쌓여 있어야**
선이 왼쪽에서 잘리지 않는다. MA120을 6개월 구간에 그리려면 대략 2년치가 필요하다.
모자라면 한 번만 더 받아두면 된다(CSV는 합쳐지므로 반복 실행해도 안전하다):

```bash
python collect.py --backfill 1825    # 전 계열 5년치 다시 받아 CSV에 합침
python build_dashboard.py
```

야후 계열은 엔드포인트가 2년까지만 주므로 `--backfill`을 더 크게 잡아도 2년에서
멈춘다. MA120에는 충분하다.

데이터를 갱신하려면 `build_dashboard.py`를 다시 돌리고 `docs/data.json`을 커밋한다
(GitHub Actions가 매일 자동으로 한다).

## 7. 텔레그램 일일 브리핑

```bash
python notify_daily.py
```

`collect.py --daily` → `upload_sheets.py --data` 를 순서대로 실행하고, 결과를
텔레그램 메시지로 보낸다(지수·종목·환율·금리·수급 요약 + 구글시트 링크). 실패하면
어느 단계에서 어떤 에러였는지를 보낸다.

봇 토큰/채팅 ID는 환경변수 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 또는
`API-KEY.txt`의 `Telegram Bot Token:` / `Telegram Chat ID:` 줄에서 읽는다.

## 8. GitHub Actions (서버 없이 매일 자동 실행)

`.github/workflows/daily.yml`이 평일 16:10 KST(07:10 UTC)에
`notify_daily.py` → `build_dashboard.py`를 실행하고 `data/`, `docs/`를
커밋·푸시한다. 설정(최초 1회):

1. **Settings → Secrets and variables → Actions → New repository secret**로 추가:
   - `KIS_APP_KEY`, `KIS_APP_SECRET` — 한국투자증권
   - `ECOS_API_KEY` — 한국은행 ECOS
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — `google-service-account.json` 파일 내용 전체(JSON 텍스트)를 그대로 붙여넣기
2. **Settings → Pages → Build and deployment → Source**를 `Deploy from a branch`,
   브랜치는 `main` / 폴더는 `/docs`로 지정. 몇 분 뒤
   `https://<계정>.github.io/<저장소>/`에서 대시보드가 뜬다.
3. 워크플로 탭에서 **Run workflow**로 최초 1회 수동 실행해 정상 동작을 확인한다.

Actions 실행 중 실패하면(토큰 만료, API 장애 등) `notify_daily.py`가 실패 사유를
텔레그램으로 보낸다. `data`/`docs` 커밋은 push 권한이 필요하므로 워크플로 상단의
`permissions: contents: write`를 지우지 말 것.
