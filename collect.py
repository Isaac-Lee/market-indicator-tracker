#!/usr/bin/env python3
"""시장 지표 수집기 (한국투자증권 Open API).

사용법:
    python collect.py --init          # 과거치 전체 수집 (최초 1회)
    python collect.py --daily         # 최근 영업일치만 갱신 (매일 18:00 KST)
    python collect.py --excel         # data/*.csv -> market_data.xlsx (구글시트 업로드용)

수집 결과는 data/<지표>.csv 에 날짜 기준으로 누적/갱신된다.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from kis_client import KIS, read_key

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CODES = json.loads((ROOT / "codes" / "instruments.json").read_text())

OHLC = ["date", "open", "high", "low", "close", "volume"]

# 지표별 수집/출력 범위: 이름 -> (기간 일수, 출력 주기 D=일 W=주)
SPEC = {
    "kospi": (183, "D"),
    "kosdaq": (183, "D"),
    "samsung_elec": (183, "D"),
    "sk_hynix": (183, "D"),
    "wti": (183, "D"),
    "usdkrw": (183, "D"),
    "usdjpy": (183, "D"),
    "ust10y": (1095, "D"),
    "ust2y": (1095, "D"),
    "ktb3y": (1095, "W"),
    "ktb10y": (1095, "W"),
    "investor_flow": (730, "W"),
    "sp500": (183, "D"),
    "nasdaq": (183, "D"),
    "dow": (183, "D"),
    "russell2000": (183, "D"),
    "dxy": (183, "D"),
    "btc": (183, "D"),
    "gold": (183, "D"),
    "oracle": (183, "D"),
    "nvidia": (183, "D"),
}


# ---------------------------------------------------------------- helpers
def ymd(d):
    return d.strftime("%Y%m%d")


def chunks(start, end, days=100):
    """KIS 기간별시세는 1회 호출당 약 100건 제한 -> 구간을 잘라서 호출."""
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def pick(row, candidates):
    for key in candidates:
        if key in row and row[key] not in ("", None):
            return row[key]
    return None


def to_frame(rows, mapping):
    """KIS 응답 행들을 공통 스키마로 정규화."""
    out = []
    for row in rows:
        rec = {col: pick(row, keys) for col, keys in mapping.items()}
        if rec.get("date"):
            out.append(rec)
    df = pd.DataFrame(out, columns=list(mapping))
    if df.empty:
        return df
    for col in df.columns:
        if col != "date":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    return df.dropna(subset=["date"]).drop_duplicates("date").sort_values("date")


PRICE_MAP = {
    "date": ["stck_bsop_date", "data_date", "bsop_date"],
    "open": ["stck_oprc", "bstp_nmix_oprc", "ovrs_nmix_oprc", "bond_oprc", "open"],
    "high": ["stck_hgpr", "bstp_nmix_hgpr", "ovrs_nmix_hgpr", "bond_hgpr", "high"],
    "low": ["stck_lwpr", "bstp_nmix_lwpr", "ovrs_nmix_lwpr", "bond_lwpr", "low"],
    "close": ["stck_clpr", "bstp_nmix_prpr", "ovrs_nmix_prpr", "bond_prpr", "last", "close"],
    "volume": ["acml_vol", "acml_tr_pbmn", "tvol", "vol"],
}


# ---------------------------------------------------------------- fetchers
def fetch_domestic_index(kis, iscd, start, end, period="D"):
    rows = []
    # 업종 시세는 응답이 약 50건에서 잘린다 -> 60일(영업일 ~41)씩 끊어 호출
    for a, b in chunks(start, end, days=60):
        body = kis.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "FHKUP03500100",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": iscd,
                "FID_INPUT_DATE_1": ymd(a),
                "FID_INPUT_DATE_2": ymd(b),
                "FID_PERIOD_DIV_CODE": period,
            },
        )
        rows += body.get("output2") or []
    return to_frame(rows, PRICE_MAP)


def fetch_domestic_stock(kis, code, start, end, period="D"):
    rows = []
    for a, b in chunks(start, end):
        body = kis.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": ymd(a),
                "FID_INPUT_DATE_2": ymd(b),
                "FID_PERIOD_DIV_CODE": period,
                "FID_ORG_ADJ_PRC": "0",  # 0: 수정주가
            },
        )
        rows += body.get("output2") or []
    return to_frame(rows, PRICE_MAP)


def fetch_overseas(kis, spec, start, end, period="D"):
    """해외지수/환율/국채 기간별시세. 코드가 바뀔 수 있어 alternates 를 순서대로 시도."""
    for code in [spec["code"]] + [c for c in spec.get("alternates", []) if c != spec["code"]]:
        rows = []
        for a, b in chunks(start, end):
            body = kis.get(
                "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice",
                "FHKST03030100",
                {
                    "FID_COND_MRKT_DIV_CODE": spec["market"],
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": ymd(a),
                    "FID_INPUT_DATE_2": ymd(b),
                    "FID_PERIOD_DIV_CODE": period,
                },
            )
            rows += body.get("output2") or []
        df = to_frame(rows, PRICE_MAP)
        if not df.empty:
            if code != spec["code"]:
                print(f"  [주의] {spec['code']} 실패 -> {code} 로 수집됨. instruments.json 갱신 권장")
            return df
    return pd.DataFrame(columns=OHLC)


MONTH_CODE = "FGHJKMNQUVXZ"


def wti_front_month(today=None):
    """WTI 근월물 코드(CL + 월코드 + 연도2자리). 만기(전월 20일경) 고려해 다음 달을 사용."""
    # ponytail: 단순 규칙(항상 다음 달). 롤오버 정확도가 필요하면 instruments.json 의 srs_cd 로 직접 지정.
    today = today or date.today()
    year, month = today.year, today.month + 1
    if month > 12:
        year, month = year + 1, 1
    return f"CL{MONTH_CODE[month - 1]}{year % 100:02d}"


YAHOO_SERIES = {
    "wti": "CL=F",           # 근월물 연결선물
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "russell2000": "^RUT",
    "dxy": "DX-Y.NYB",       # ICE 달러지수
    "btc": "BTC-USD",        # 24시간 시장이라 주말에도 값이 나온다
    "gold": "GC=F",          # COMEX 금 선물
    "oracle": "ORCL",
    "nvidia": "NVDA",
}


def fetch_yahoo(symbol, start, end, rng="2y"):
    """Yahoo chart 엔드포인트에서 일봉 OHLC를 받는다. 키 불필요.

    야후 비공식 엔드포인트라 스펙이 바뀔 수 있어 실패하면 그대로 예외를 올린다.
    당일 미체결 봉은 close가 None으로 오므로 dropna로 버린다.
    """
    import requests

    res = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": rng, "interval": "1d"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    res.raise_for_status()
    chart = res.json()["chart"]["result"][0]
    quote = chart["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(chart["timestamp"], unit="s").normalize(),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        }
    ).dropna(subset=["close"])
    mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    return df[mask].drop_duplicates("date").sort_values("date")


def fetch_wti(kis, start, end):
    spec = CODES["futures"]["wti"]
    srs = spec.get("srs_cd") or wti_front_month(end)
    rows, cursor = [], end
    while cursor >= start:
        try:
            body = kis.get(
                "/uapi/overseas-futureoption/v1/quotations/daily-ccnl",
                "HHDFC55020100",
                {
                    "SRS_CD": srs,
                    "EXCH_CD": spec["exch_cd"],
                    "START_DATE_TIME": "",
                    "CLOSE_DATE_TIME": ymd(cursor),
                    "QRY_TP": "Q",
                    "QRY_CNT": "40",
                    "QRY_GAP": "",
                    "INDEX_KEY": "",
                },
            )
        except Exception as exc:
            if "EGW00551" in str(exc) or "SUB거래소" in str(exc):
                print(f"  [정보] {srs}: NYMEX 시세 미신청 계좌 -> 야후 CL=F로 대체 "
                      f"(KIS로 받으려면 HTS/MTS에서 해외선물 NYMEX 시세 신청)")
                return fetch_yahoo(YAHOO_SERIES["wti"], start, end)
            raise
        batch = body.get("output2") or []
        if not batch:
            break
        rows += batch
        dates = [d for d in (pick(r, PRICE_MAP["date"]) for r in batch) if d]
        if not dates:
            break
        oldest = datetime.strptime(min(dates), "%Y%m%d").date()
        if oldest <= start:
            break
        cursor = oldest - timedelta(days=1)
    df = to_frame(rows, PRICE_MAP)
    return df[df["date"] >= pd.Timestamp(start)] if not df.empty else df


def fetch_ecos_rate(spec, start, end):
    """한국은행 ECOS 시장금리(일별)에서 금리(연%)를 받는다.

    KIS 장내채권 API는 개별 채권의 '가격'만 주고 금리를 주지 않아 지표로 쓸 수 없다(실계좌 확인).
    ECOS 인증키(무료, https://ecos.bok.or.kr/api)는 ECOS_API_KEY 환경변수 또는
    API-KEY.txt 의 `ECOS Key:` 줄에서 읽는다. 없으면 건너뛴다(import_ecos.py 로 수동 적재).
    """
    import requests

    key = read_key(r"ECOS\s*Key", "ECOS_API_KEY")
    if not key:
        print("  [건너뜀] ECOS_API_KEY 없음 -> import_ecos.py 로 수동 적재 필요")
        return pd.DataFrame()
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/"
        f"{spec['ecos_stat']}/D/{ymd(start)}/{ymd(end)}/{spec['ecos_item']}"
    )
    body = requests.get(url, timeout=20).json()
    rows = body.get("StatisticSearch", {}).get("row")
    if not rows:
        raise RuntimeError(f"ECOS 응답 이상: {str(body)[:200]}")
    df = pd.DataFrame({"date": [r["TIME"] for r in rows], "close": [r["DATA_VALUE"] for r in rows]})
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna().sort_values("date")


# 실계좌 응답으로 확인한 필드명 (단위: 순매수 거래대금 백만원)
INVESTOR_MAP = {
    "date": ["stck_bsop_date"],
    "foreign": ["frgn_ntby_tr_pbmn"],        # 외국인 (등록+미등록 합)
    "institution": ["orgn_ntby_tr_pbmn"],    # 기관계
    "individual": ["prsn_ntby_tr_pbmn"],     # 개인
    "pension": ["fund_ntby_tr_pbmn"],        # 연기금등
    "trust": ["ivtr_ntby_tr_pbmn"],          # 투신
    "close": ["bstp_nmix_prpr"],             # 해당 시장 지수 종가(참고용)
}


def fetch_investor(kis, start, end):
    """시장별 투자자매매동향(일별).

    1회 호출이 요청일 기준 과거 300영업일을 한 번에 돌려준다 -> 커서를 뒤로 밀며 몇 번만 호출.
    """
    spec = CODES["investor_market"]
    rows, cursor, warned = [], end, False
    while cursor >= start:
        body = kis.get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
            "FHPTJ04040000",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": spec["iscd"],
                "FID_INPUT_DATE_1": ymd(cursor),
                "FID_INPUT_ISCD_1": spec["market"],
                "FID_INPUT_DATE_2": ymd(cursor),
                "FID_INPUT_ISCD_2": spec["iscd"],
            },
        )
        batch = body.get("output") or []
        if isinstance(batch, dict):
            batch = [batch]
        if not batch:
            break
        if not warned:
            missing = [k for k, v in INVESTOR_MAP.items() if pick(batch[0], v) is None]
            if missing:
                print(f"  [주의] 투자자 필드 미매핑: {missing} / 응답필드: {list(batch[0])}")
            warned = True
        rows += batch
        dates = [r.get("stck_bsop_date") for r in batch if r.get("stck_bsop_date")]
        oldest = datetime.strptime(min(dates), "%Y%m%d").date()
        if oldest <= start:
            break
        cursor = oldest - timedelta(days=1)
    df = to_frame(rows, INVESTOR_MAP)
    return df[df["date"] >= pd.Timestamp(start)] if not df.empty else df


FRED_SERIES = {"ust10y": "DGS10", "ust2y": "DGS2"}


def fetch_fred(series_id, start, end):
    """FRED CSV에서 일별 금리(연%)를 받는다. 키 불필요.

    KIS에는 미국채 시계열이 없다 — .TNX/TNX/^TNX/.IRX/.FVX/.TYX/BY0202를 시장코드
    I/N/S/X 조합으로 전부 시도했지만 오류 없이 빈 응답만 왔다(2026-08-04 실계좌 확인).
    FRED는 하루 지연된다(2026-08-23 조회 시 마지막이 08-20). stale 임계 5일이 흡수한다.
    """
    import io

    import requests

    res = requests.get(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=20
    )
    res.raise_for_status()
    df = pd.read_csv(io.StringIO(res.text))
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")  # 휴장일은 "."로 온다
    df = df.dropna()
    mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    return df[mask][["date", "close"]].sort_values("date")


# ---------------------------------------------------------------- storage
def save(name, df):
    if df is None or df.empty:
        print(f"  [경고] {name}: 수집 데이터 없음")
        return
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{name}.csv"
    if path.exists():
        old = pd.read_csv(path, parse_dates=["date"])
        df = pd.concat([old, df]).drop_duplicates("date", keep="last").sort_values("date")
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"  {name}: {len(df)}행 -> {path.name}")


# ---------------------------------------------------------------- 신선도 판정
# 주말 2일에 연휴 3일까지 흡수한다. 그보다 오래 낡은 것은 정상적인 휴장으로
# 설명되지 않는다. 계열별로 다른 임계를 두지 않는다 — 소스마다 숫자가 다르면
# 어느 소스가 어떤 임계였는지 기억해야 하고, 실제로 필요한 것은 "며칠 넘게 안
# 들어오면 이상하다" 하나뿐이다.
STALE_LIMIT_DAYS = 5


def last_data_dates(names):
    """{계열: 마지막 데이터 날짜}. CSV가 없거나 비었으면 None."""
    out = {}
    for name in names:
        path = DATA / f"{name}.csv"
        if not path.exists():
            out[name] = None
            continue
        df = pd.read_csv(path, parse_dates=["date"])
        out[name] = None if df.empty else df["date"].max().date()
    return out


def stale_series(last, today, limit_days=STALE_LIMIT_DAYS):
    """[(계열, 마지막날짜|None)] — 낡았거나 한 번도 안 들어온 계열. 이름순."""
    out = []
    for name in sorted(last):
        when = last[name]
        if when is None or (today - when).days > limit_days:
            out.append((name, when))
    return out


def summary_line(total, stale):
    """다이제스트가 가져갈 한 줄. 개행을 넣지 않는다(다이제스트 spec 3.1)."""
    if not stale:
        return f"{total}계열 갱신 · stale 0"
    detail = ", ".join(
        f"{name} 마지막 {when.strftime('%m-%d') if when else '없음'}" for name, when in stale
    )
    return f"{total}계열 갱신 · stale {len(stale)} ({detail})"


def collect(days_back=None):
    today = date.today()
    clients = {}

    def client(kind):
        """KIS 인스턴스는 실제로 쓸 때만 만든다(토큰 발급 = 네트워크 호출)."""
        if kind not in clients:
            clients[kind] = KIS()
        return clients[kind]

    def since(name):
        """SPEC 기간만큼 거슬러 올라간 시작일 (--daily 면 최근 며칠만)."""
        if days_back:
            return today - timedelta(days=days_back)
        return today - timedelta(days=SPEC[name][0])

    jobs = {
        "kospi": lambda: fetch_domestic_index(client("kis"), CODES["domestic_index"]["kospi"], since("kospi"), today),
        "kosdaq": lambda: fetch_domestic_index(client("kis"), CODES["domestic_index"]["kosdaq"], since("kosdaq"), today),
        "samsung_elec": lambda: fetch_domestic_stock(client("kis"), CODES["domestic_stock"]["samsung_elec"], since("samsung_elec"), today),
        "sk_hynix": lambda: fetch_domestic_stock(client("kis"), CODES["domestic_stock"]["sk_hynix"], since("sk_hynix"), today),
        "usdkrw": lambda: fetch_overseas(client("kis"), CODES["overseas"]["usdkrw"], since("usdkrw"), today),
        "usdjpy": lambda: fetch_overseas(client("kis"), CODES["overseas"]["usdjpy"], since("usdjpy"), today),
        "wti": lambda: fetch_wti(client("kis"), since("wti"), today),
        "investor_flow": lambda: fetch_investor(client("kis"), since("investor_flow"), today),
    }

    for name in ("sp500", "nasdaq", "dow", "russell2000", "dxy", "btc", "gold", "oracle", "nvidia"):
        jobs[name] = (lambda n=name: fetch_yahoo(YAHOO_SERIES[n], since(n), today))

    for name in FRED_SERIES:
        jobs[name] = (lambda n=name: fetch_fred(FRED_SERIES[n], since(n), today))

    for name in ("ktb3y", "ktb10y"):
        jobs[name] = (lambda n=name: fetch_ecos_rate(CODES["bond"][n], since(n), today))

    for name, job in jobs.items():
        print(f"[{name}] 수집 중...")
        try:
            save(name, job())
        except Exception as exc:  # 한 지표 실패가 나머지를 막지 않도록
            print(f"  [실패] {name}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------- 출력용 가공
SUM_COLS = ["foreign", "institution", "individual", "pension", "trust"]


def derive_investor(df):
    """누적 순매수 + 외국인 4주 이동평균 (주간 데이터 기준 rolling 4)."""
    df = df.sort_values("date").copy()
    for col in ("foreign", "institution", "individual", "pension"):
        if col in df:
            df[f"{col}_cum"] = df[col].cumsum()
    if "foreign" in df:
        df["foreign_ma4w"] = df["foreign"].rolling(4).mean()
        df["foreign_cum_ma4w"] = df["foreign_cum"].rolling(4).mean()
    return df


def for_output(name, df, today=None, trim=True):
    """SPEC에 맞춰 기간을 자르고 주간 지표는 주(금) 단위로 묶는다.

    trim=False 면 기간을 자르지 않고 쌓인 데이터를 전부 준다. 이동평균처럼
    앞쪽 데이터를 먹는 보조지표는 잘린 구간만으로는 앞부분이 비어버린다.
    """
    days, freq = SPEC.get(name, (None, "D"))
    df = df.sort_values("date")
    if days and trim:
        start = pd.Timestamp((today or date.today()) - timedelta(days=days))
        df = df[df["date"] >= start]
    if freq == "W":
        idx = df.set_index("date")
        if name == "investor_flow":  # 순매수는 주간 합계, 지수 종가는 주 마지막 값
            agg = {c: "sum" for c in SUM_COLS if c in idx.columns}
            agg.update({c: "last" for c in idx.columns if c not in agg})
            df = idx.resample("W-FRI").agg(agg).dropna(how="all").reset_index()
        else:
            df = idx.resample("W-FRI").last().dropna(how="all").reset_index()
    if name == "investor_flow":
        df = derive_investor(df)
    return df.reset_index(drop=True)


def output_frames(today=None, trim=True):
    """{시트명: 출력용 DataFrame}. 엑셀·구글시트 양쪽이 같은 가공을 쓴다."""
    frames = {}
    for csv in sorted(DATA.glob("*.csv")):
        frames[csv.stem] = for_output(
            csv.stem, pd.read_csv(csv, parse_dates=["date"]), today, trim=trim
        )
    return frames


# ---------------------------------------------------------------- 스냅샷 표
# CLAUDE.md의 observation 시장 스냅샷 표. 항목 이름과 순서를 그 문서에 맞춘다.
# (표시명, 계열, 열). 계열이 ""이면 수집하지 않는 항목이다.
SNAPSHOT_KR = [
    ("KOSPI", "kospi", "close"),
    ("KOSDAQ", "kosdaq", "close"),
    ("주도주1 삼성전자", "samsung_elec", "close"),
    ("주도주2 SK하이닉스", "sk_hynix", "close"),
    ("원달러", "usdkrw", "close"),
    ("달러엔", "usdjpy", "close"),
    ("국고채 3년", "ktb3y", "close"),
    ("국고채 10년", "ktb10y", "close"),
    ("수급 외국인(백만원)", "investor_flow", "foreign"),
    ("수급 기관(백만원)", "investor_flow", "institution"),
    ("수급 개인(백만원)", "investor_flow", "individual"),
]

SNAPSHOT_US = [
    ("나스닥", "nasdaq", "close"),
    ("미국채 10년", "ust10y", "close"),
    ("비트코인", "btc", "close"),
    ("금", "gold", "close"),
    ("WTI", "wti", "close"),
    ("엔비디아", "nvidia", "close"),
    ("오라클", "oracle", "close"),
]

# 금리는 bp 단위로 읽으므로 소수 3자리, 순매수는 백만원 정수. 나머지는 2자리.
DECIMALS = {"ktb3y": 3, "ktb10y": 3, "investor_flow": 0}

# 순매수 금액 자체가 이미 흐름이라 "전일 대비 순매수의 변동"은 해석되지 않는
# 숫자다. 못 구한 값(미확인)과 구분해야 한다 — 미확인으로 적으면 나중에 그
# 자리를 보고 조회가 실패했다고 오해한다.
NO_DELTA = {"investor_flow"}


def series_pair(df, col, on):
    """(on 이하 마지막 값, 그 직전 값). 없으면 None. 휴장일 조회도 직전 거래일로 잡힌다."""
    if df is None or df.empty or col not in df.columns:
        return None, None
    rows = df[df["date"] <= pd.Timestamp(on)].dropna(subset=[col]).sort_values("date")
    if rows.empty:
        return None, None
    cur = float(rows.iloc[-1][col])
    prev = float(rows.iloc[-2][col]) if len(rows) >= 2 else None
    return cur, prev


def snapshot_row(label, name, cur, prev):
    """markdown 표 한 행. 빈칸을 두지 않는다 — 못 구한 값은 미확인(CLAUDE.md)."""
    nd = DECIMALS.get(name, 2)
    if cur is None:
        return f"| {label} | 미확인 | 미확인 | 미확인 |"
    value = f"{cur:,.{nd}f}"
    if name in NO_DELTA:
        return f"| {label} | {value} | — | — |"
    if prev is None:
        return f"| {label} | {value} | 미확인 | 미확인 |"
    diff = cur - prev
    pct = (diff / prev * 100) if prev else None
    diff_s = f"{diff:+,.{nd}f}"
    pct_s = f"{pct:+.2f}%" if pct is not None else "미확인"
    return f"| {label} | {value} | {diff_s} | {pct_s} |"


def render_snapshot(on=None):
    """CLAUDE.md 형식의 한국 / 미국·글로벌 표 두 개."""
    on = on or date.today()
    cache = {}

    def frame(name):
        if name and name not in cache:
            path = DATA / f"{name}.csv"
            cache[name] = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
        return cache.get(name)

    out = []
    for title, rows in (("한국", SNAPSHOT_KR), ("미국·글로벌", SNAPSHOT_US)):
        out.append(f"**{title}**\n")
        out.append("| 항목 | 값 | 변동 | % |")
        out.append("|---|---|---|---|")
        for label, name, col in rows:
            cur, prev = series_pair(frame(name), col, on) if name else (None, None)
            out.append(snapshot_row(label, name, cur, prev))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def to_excel(path=ROOT / "market_data.xlsx"):
    frames = output_frames()
    if not frames:
        sys.exit("data/*.csv 없음. 먼저 python collect.py --init 실행")
    with pd.ExcelWriter(path, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        for name, df in frames.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
            print(f"  {name}: {len(df)}행 ({SPEC.get(name, ('', 'D'))[1]})")
    print(f"생성: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="과거치 전체 수집")
    ap.add_argument("--daily", action="store_true", help="최근 영업일치 갱신")
    ap.add_argument("--days", type=int, default=10, help="--daily 시 조회할 최근 일수")
    ap.add_argument("--excel", action="store_true", help="CSV -> xlsx 변환")
    ap.add_argument("--snapshot", nargs="?", const="", metavar="YYYY-MM-DD",
                    help="CLAUDE.md 형식 시장 스냅샷 표를 출력 (기본: 오늘)")
    args = ap.parse_args()
    if args.snapshot is not None:
        on = date.fromisoformat(args.snapshot) if args.snapshot else date.today()
        print(render_snapshot(on), end="")
        return 0
    if args.init:
        collect()
    if args.daily:
        collect(days_back=args.days)
    if args.excel or args.init:
        to_excel()
    if args.init or args.daily:
        names = sorted(SPEC)
        stale = stale_series(last_data_dates(names), date.today())
        # 요약 줄은 반드시 마지막에 찍는다. run_job.py가 stdout의 마지막 줄을
        # 그대로 다이제스트 summary로 가져간다(다이제스트 spec 3.1).
        print(summary_line(len(names), stale))
        if stale and len(stale) == len(names):
            # 전 계열이 멈춘 것은 네트워크나 키 문제라 job 실패가 맞다.
            # 일부만 낡은 것은 0으로 둔다 — 계열 하나 때문에 매일 ❌를 띄우면
            # ❌ 자체가 무뎌진다.
            return 1
    if not (args.init or args.daily or args.excel):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
