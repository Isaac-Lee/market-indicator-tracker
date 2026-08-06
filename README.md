# Market Indicator Tracker

어둠의 알상무단을 위한 지표추적자 (Market Indicator Tracker)

토스증권 / 한국투자증권 Open API로 시장 지표를 로컬에 수집하고, 구글 시트에 올릴 엑셀 파일을 만드는 도구.

## 1. 설치 / 인증

```bash
pip install -r requirements.txt
```

키는 환경변수가 우선이고, 없으면 저장소 안의 `API-KEY.txt`를 읽는다(`.gitignore` 등록됨).

```
APP Key: ...           # 한국투자증권
APP Secret: ...
ECOS Key: ...          # 한국은행 ECOS 인증키 (국고채 3년 대체 경로)
Toss Client ID: ...    # 토스증권 (WTS > 설정 > Open API)
Toss Client Secret: ...
```

환경변수로 넘길 경우:

```bash
export KIS_APP_KEY=... KIS_APP_SECRET=... ECOS_API_KEY=...
export KIS_ENV=prod   # 모의투자면 vps
export TOSS_CLIENT_ID=... TOSS_CLIENT_SECRET=...
```

접근토큰은 `~/.kis_token.json` / `~/.toss_token.json`에 캐시되며(권한 600) 만료 10분 전까지 재사용한다.
KIS는 토큰 발급을 1분에 1회로 제한하고, 토스는 client당 유효 토큰이 1개(재발급 시 이전 토큰 즉시 무효)이므로
캐시를 지우지 말 것.

토스는 **허용 IP 등록이 필수**다. WTS > 설정 > Open API > 허용 IP 관리에 호출 IP를 넣지 않으면 403이 난다.

## 2. 실행

이 맥에는 `/usr/local/bin/python3`(3.14, 패키지 없음)가 PATH 앞에 있다. 의존성이 깔린 쪽은
`/usr/bin/python3` 이므로 **`/usr/bin/python3` 로 실행**할 것 (`ModuleNotFoundError: pandas` 나면 이 문제).

```bash
/usr/bin/python3 collect.py --daily        # 오늘치 추가 (매일)
/usr/bin/python3 upload_sheets.py --data   # 구글 시트 반영
```

```bash
python collect.py --init      # 과거치 전체 수집 + market_data.xlsx 생성 (최초 1회)
python collect.py --daily     # 최근 10영업일 갱신 (매일)
python collect.py --excel     # data/*.csv -> market_data.xlsx 재생성
python import_ecos.py "시장금리(일별)_04000531.xlsx"   # ECOS 엑셀 -> data/ktb3y.csv
python test_collect.py        # 네트워크 없이 로직 검증
```

수집 결과는 `data/<지표>.csv`에 날짜 기준으로 누적된다(같은 날짜는 최신값으로 덮어씀).
종목·지수 코드는 전부 `codes/instruments.json`에 있다. 코드가 바뀌면 그 파일만 고치면 된다.

## 2.5. 데이터 소스 (토스증권 / 한국투자증권)

`--source` 로 고른다. 기본은 `auto`.

```bash
python collect.py --daily --source auto   # 토스 지원 지표는 토스, 실패하면 KIS로 자동 대체 (기본)
python collect.py --daily --source toss   # 토스만 (미지원 지표는 기존 KIS/FRED/야후 경로 그대로)
python collect.py --daily --source kis    # 기존 KIS 경로만
```

| 지표 | 토스 엔드포인트 | 비고 |
|---|---|---|
| `kospi` / `kosdaq` | `/api/v1/market-indicators/{KOSPI\|KOSDAQ}/candles` | KIS 값과 **완전 일치**(거래량은 주 단위로 와서 1000으로 나눠 천주로 맞춤) |
| `ktb3y` | `/api/v1/market-indicators/KR_BOND_3Y/candles` | 종가 = 수익률 연%. ECOS 값과 일치 → **ECOS 키 없이도 수집된다** |
| `samsung_elec` / `sk_hynix` | `/api/v1/candles` (`adjusted=true`) | ⚠ KIS와 값이 다르다(아래) |
| `investor_flow` | `/api/v1/market-indicators/{KOSPI}/investor-trading` | ⚠ KIS와 값이 다르다(아래). 원 단위 매수-매도 → 백만원으로 환산 |
| `wti`, `usdkrw`, `usdjpy`, `ust10y_weekly` | 없음 | 토스는 환율 **현재가**만 주고 시계열이 없다. 기존 경로 유지 |

⚠ **개별 종목·수급은 두 소스를 섞지 말 것.** 2026-08-03 삼성전자 종가가 KIS 239,500 / 토스 233,500,
거래량 27.8M / 53.0M로 다르다(토스는 KRX+NXT 통합 기준으로 보인다). 투자자 매매대금도 마찬가지로
외국인 순매수가 KIS -2,822,021 / 토스 -3,851,193 백만원이다. 토스로 갈아탄다면
`data/samsung_elec.csv`, `data/sk_hynix.csv`, `data/investor_flow.csv` 를 지우고 `--init` 으로 다시 받아
계열을 한 소스로 통일해야 한다. `kospi`/`kosdaq`/`ktb3y`는 값이 같아 그냥 이어 붙여도 된다.

Rate limit은 클라이언트×API그룹 단위 TPS(차트 5회/초)라 `toss_client.py`가 0.21초 간격 + 429 시
`Retry-After` 백오프로 처리한다.

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
| `ust10y_weekly` | 미국채 10년 금리 | **FRED `DGS10`** (KIS 미지원) | 주(금) | 3년 | 156 |
| `ktb3y` | 국고채 3년 금리 | **한국은행 ECOS** `817Y002`/`010200000` | 주(금) | 3년 | 157 |
| `investor_flow` | 주체별 순매수(외국인/기관/개인/연기금/투신) | 시장별 투자자매매동향(일별) `FHPTJ04040000` | 주(금) | 2년 | 105 |

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
  KIS 해외지수 시세를 신청해 조회가 가능해지면 `codes/instruments.json`의 `_ust10y` 항목명을
  `ust10y`로 바꾸면 된다. 그때는 KIS를 먼저 시도하고 빈 응답이면 FRED로 자동 대체한다.
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

## 4. 매일 18:00(KST) 자동 갱신

로컬 cron이 가장 단순하다.

```bash
crontab -e
```

```cron
0 18 * * 1-5 cd ~/Desktop/스펙/투자/market-indicator-tracker && /usr/bin/python3 collect.py --daily --excel >> update.log 2>&1
```

Claude Code에서 돌릴 경우, 이 저장소에서 다음 프롬프트로 스케줄 작업을 만들면 된다:

> 매일 평일 18:00 KST에 `python collect.py --daily --excel`을 실행하고, 실패한 지표가 있으면 알려줘.

`--daily`는 최근 10일을 다시 받아 같은 날짜를 덮어쓰므로, 하루 이틀 걸러 실행해도 구멍이 나지 않는다.
휴장일에는 빈 응답이 오고 파일은 그대로 유지된다.

## 5. 구글 시트 업로드 + 대시보드

대상 시트: [지표추적자](https://docs.google.com/spreadsheets/d/1WH8AhW_fjKzmw4S6H90CJI-fYPLaba4DtsAr_lmN3t8/edit)
(ID는 `upload_sheets.py`의 `SPREADSHEET_ID` 상수)

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

- 지표별 시트: `kospi`, `kosdaq`, `samsung_elec`, `sk_hynix`, `usdkrw`, `usdjpy`, `wti`,
  `ust10y_weekly`, `ktb3y`, `investor_flow` — 매 실행마다 전체 덮어쓰기(중복·순서 걱정 없음)
- `dashboard` 시트(맨 앞): 차트 11개, 760x570px(4:3), 2열 격자. 배치는 `upload_sheets.py`의
  `LAYOUT` 리스트가 그대로 화면 순서다.

  | 행 | 왼쪽 | 오른쪽 |
  |---|---|---|
  | 1 | 외국인 누적 순매수 + 4주 MA | 주체별 누적 순매수(외국인/기관/개인/연기금) |
  | 2 | KOSPI 캔들 | KOSDAQ 캔들 |
  | 3 | 미국채 10년 금리 | 국고채 3년 금리 |
  | 4 | WTI 원유 선물 캔들 | — |
  | 5 | 삼성전자 캔들 | SK하이닉스 캔들 |
  | 6 | 원달러 환율 캔들 | 달러엔 환율 캔들 |

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
0 18 * * 1-5 cd ~/Desktop/스펙/투자/market-indicator-tracker && /usr/bin/python3 collect.py --daily && /usr/bin/python3 upload_sheets.py --data >> update.log 2>&1
```

차트는 데이터 범위를 행 수까지 잡아두므로, 행이 늘면 `--charts`를 가끔(월 1회 정도) 다시 돌리면 된다.
