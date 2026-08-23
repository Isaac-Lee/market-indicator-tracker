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
    "ust10y_weekly": (1095, "W"),
    "ktb3y": (1095, "W"),
    "investor_flow": (730, "W"),
    "sp500": (183, "D"),
    "nasdaq": (183, "D"),
    "dow": (183, "D"),
    "russell2000": (183, "D"),
    "dxy": (183, "D"),
    "btc": (183, "D"),
    "gold": (183, "D"),
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


def fetch_ktb3y(start, end):
    """국고채 3년 금리(연%) — 한국은행 ECOS.

    KIS 장내채권 API는 개별 채권의 '가격'만 주고 금리를 주지 않아 지표로 쓸 수 없다(실계좌 확인).
    ECOS 인증키(무료, https://ecos.bok.or.kr/api)는 ECOS_API_KEY 환경변수 또는
    KIS-API-KEY.txt 의 `ECOS Key:` 줄에서 읽는다. 없으면 건너뛴다(import_ecos.py 로 수동 적재).
    """
    import requests

    spec = CODES["bond"]["ktb3y"]
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


FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"


def fetch_ust10y(start, end, kis=None):
    """미국채 10년 금리(주간).

    `codes/instruments.json`에 `overseas.ust10y`가 있으면 KIS를 먼저 시도하고,
    빈 응답이면 FRED DGS10 CSV(키 불필요)로 대체해 주간(금요일) 종가로 리샘플한다.
    이 계좌에서는 .TNX/TNX/^TNX/.IRX/.FVX/.TYX/BY0202 모두 빈 응답이라 FRED가 쓰인다.
    """
    import io

    import requests

    spec = CODES["overseas"].get("ust10y")
    if kis is not None and spec:
        df = fetch_overseas(kis, spec, start, end, period="W")
        if not df.empty:
            return df[["date", "open", "high", "low", "close"]]
        print("  [정보] KIS 미국채 코드 빈 응답 -> FRED DGS10 사용")

    res = requests.get(FRED_URL, timeout=20)
    res.raise_for_status()
    df = pd.read_csv(io.StringIO(res.text))
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna()
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    weekly = df.set_index("date").resample("W-FRI").last().dropna().reset_index()
    return weekly[["date", "close"]]


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
        "ust10y_weekly": lambda: fetch_ust10y(since("ust10y_weekly"), today, client("kis")),
        "wti": lambda: fetch_wti(client("kis"), since("wti"), today),
        "ktb3y": lambda: fetch_ktb3y(since("ktb3y"), today),
        "investor_flow": lambda: fetch_investor(client("kis"), since("investor_flow"), today),
    }

    for name in ("sp500", "nasdaq", "dow", "russell2000", "dxy", "btc", "gold"):
        jobs[name] = (lambda n=name: fetch_yahoo(YAHOO_SERIES[n], since(n), today))

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


def for_output(name, df, today=None):
    """SPEC에 맞춰 기간을 자르고 주간 지표는 주(금) 단위로 묶는다."""
    days, freq = SPEC.get(name, (None, "D"))
    df = df.sort_values("date")
    if days:
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


def output_frames(today=None):
    """{시트명: 출력용 DataFrame}. 엑셀·구글시트 양쪽이 같은 가공을 쓴다."""
    frames = {}
    for csv in sorted(DATA.glob("*.csv")):
        frames[csv.stem] = for_output(csv.stem, pd.read_csv(csv, parse_dates=["date"]), today)
    return frames


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
    args = ap.parse_args()
    if args.init:
        collect()
    if args.daily:
        collect(days_back=args.days)
    if args.excel or args.init:
        to_excel()
    if not (args.init or args.daily or args.excel):
        ap.print_help()


if __name__ == "__main__":
    main()
