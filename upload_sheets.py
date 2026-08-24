#!/usr/bin/env python3
"""data/*.csv 를 구글 시트에 올리고 dashboard 시트에 차트를 만든다.

    python upload_sheets.py            # 데이터 업로드 + 대시보드 생성
    python upload_sheets.py --data     # 데이터만
    python upload_sheets.py --charts   # 대시보드만 재생성

사전 준비(1회):
 1) Google Cloud 콘솔에서 서비스 계정 생성 -> JSON 키 발급 -> google-service-account.json 으로 저장
 2) Google Sheets API 사용 설정
 3) 대상 스프레드시트를 서비스 계정 이메일에 '편집자'로 공유
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from collect import DATA, SPEC, output_frames

SPREADSHEET_ID = "1WH8AhW_fjKzmw4S6H90CJI-fYPLaba4DtsAr_lmN3t8"
CRED_FILE = Path(__file__).parent / "google-service-account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 캔들차트로 그릴 지표 (CSV 열 순서: date, open, high, low, close, volume)
CANDLE = ["kospi", "kosdaq", "samsung_elec", "sk_hynix", "usdkrw", "usdjpy", "wti"]
# 선 그래프로 그릴 지표 -> (시트, 값 열 이름들)
LINES = [
    ("ktb3y", ["close"]),
    ("ust10y", ["close"]),
    ("investor_flow", ["foreign_cum", "foreign_cum_ma4w"]),
    ("investor_flow", ["foreign_cum", "institution_cum", "individual_cum", "pension_cum"]),
]
TITLES = {
    "kospi": "KOSPI",
    "kosdaq": "KOSDAQ",
    "samsung_elec": "삼성전자",
    "sk_hynix": "SK하이닉스",
    "usdkrw": "원달러 환율",
    "usdjpy": "달러엔 환율",
    "wti": "WTI 원유 선물",
    "ktb3y": "국고채 3년 금리",
    "ust10y": "미국채 10년 금리",
    ("ktb3y", ("close",)): "국고채 3년 금리",
    ("ust10y", ("close",)): "미국채 10년 금리",
    ("investor_flow", ("foreign_cum", "foreign_cum_ma4w")): "외국인 누적 순매수 + 4주 MA",
    ("investor_flow", ("foreign_cum", "institution_cum", "individual_cum", "pension_cum")):
        "주체별 누적 순매수",
}
DASHBOARD = "dashboard"
BRIEFING = "briefing"
CHART_W, CHART_H = 760, 570  # 4:3, 캔들이 보이도록 크게
GRID_ROWS, GRID_COLS = 28, 8  # 차트 하나가 차지하는 셀 수(anchor 간격)

# 대시보드 배치: 행 단위로 왼쪽 -> 오른쪽. 캔들은 시트명, 선 그래프는 (시트명, 열들)
LAYOUT = [
    [("investor_flow", ["foreign_cum", "foreign_cum_ma4w"]),
     ("investor_flow", ["foreign_cum", "institution_cum", "individual_cum", "pension_cum"])],
    ["kospi", "kosdaq"],
    [("ust10y", ["close"]), ("ktb3y", ["close"])],
    ["wti"],
    ["samsung_elec", "sk_hynix"],
    ["usdkrw", "usdjpy"],
]


def service():
    if not CRED_FILE.exists():
        sys.exit(f"{CRED_FILE.name} 없음. 서비스 계정 JSON 키를 이 경로에 두고 시트를 공유할 것")
    creds = Credentials.from_service_account_file(str(CRED_FILE), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def sheet_ids(api):
    meta = api.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}


def frames():
    """업로드할 {시트명: DataFrame} — 기간·주기 가공은 collect.for_output 이 담당."""
    out = output_frames()
    if not out:
        sys.exit("data/*.csv 없음. 먼저 python collect.py --init 실행")
    for df in out.values():
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return out


def push_data(api, data):
    existing = sheet_ids(api)
    add = [
        {"addSheet": {"properties": {"title": name}}}
        for name in data
        if name not in existing
    ]
    if add:
        api.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": add}).execute()

    body = {
        # RAW: 날짜를 '2024-08-05' 문자열 그대로 둔다.
        # 구글 캔들차트는 도메인(1열)이 반드시 텍스트여야 해서, 날짜형으로 변환되면 "1열은 텍스트여야 합니다" 오류가 난다.
        "valueInputOption": "RAW",
        "data": [
            {
                "range": f"{name}!A1",
                "values": [list(df.columns)] + df.where(pd.notna(df), "").values.tolist(),
            }
            for name, df in data.items()
        ],
    }
    for name in data:
        api.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{name}!A:Z").execute()
    api.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
    for name, df in data.items():
        print(f"  {name}: {len(df)}행 x {len(df.columns)}열")


def build_briefing_text():
    """data/*.csv 최신 행 기준 오늘 브리핑 텍스트."""
    import datetime

    lines = [f"{datetime.date.today():%Y-%m-%d} 시장 브리핑", ""]

    for name in CANDLE + ["ktb3y", "ust10y"]:
        path = DATA / f"{name}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if len(df) < 1:
            continue
        cur = df.iloc[-1]
        title = TITLES.get(name, name)
        if len(df) >= 2 and pd.notna(cur["close"]) and pd.notna(df.iloc[-2]["close"]):
            prev_close = df.iloc[-2]["close"]
            diff = cur["close"] - prev_close
            pct = diff / prev_close * 100 if prev_close else 0
            lines.append(f"{title}: {cur['close']:,.2f} ({diff:+,.2f}, {pct:+.2f}%)")
        else:
            lines.append(f"{title}: {cur['close']:,.2f}")

    flow_path = DATA / "investor_flow.csv"
    if flow_path.exists():
        df = pd.read_csv(flow_path)
        if len(df) >= 1:
            cur = df.iloc[-1]
            lines.append("")
            lines.append(
                f"투자자별 순매수(외국인/기관/개인): "
                f"{cur['foreign']:+,.0f} / {cur['institution']:+,.0f} / {cur['individual']:+,.0f}"
            )

    return "\n".join(lines)


def push_briefing(api):
    existing = sheet_ids(api)
    if BRIEFING not in existing:
        api.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": BRIEFING}}}]},
        ).execute()
    api.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{BRIEFING}!A:Z"
    ).execute()
    api.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{BRIEFING}!A1",
        valueInputOption="RAW",
        body={"values": [[build_briefing_text()]]},
    ).execute()
    print(f"  {BRIEFING}: 텍스트 브리핑 갱신")


def period_label(name):
    days, freq = SPEC.get(name, (0, "D"))
    unit = "일" if freq == "D" else "주"
    span = {183: "6개월", 365: "1년", 730: "2년", 1095: "3년"}.get(days, f"{days}일")
    return f"({unit}, {span})"


def chart_title(name):
    return f"{TITLES.get(name, name)} {period_label(name)}"


def col_range(sid, col, rows, start=0):
    return {
        "sourceRange": {
            "sources": [
                {
                    "sheetId": sid,
                    "startRowIndex": start,
                    "endRowIndex": rows + 1,
                    "startColumnIndex": col,
                    "endColumnIndex": col + 1,
                }
            ]
        }
    }


def candle_chart(title, sid, rows, anchor, cols):
    """구글 캔들차트. 헤더행 제외.

    색상은 지정할 수 없다. Sheets는 캔들 시리즈 그룹을 1개만 허용하고
    (`More than 1 candlestickChartSpec.data is not supported`) 색 필드도 없다.
    """
    rng = lambda col: col_range(sid, col, rows, start=1)  # noqa: E731
    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "candlestickChart": {
                        "domain": {"data": rng(0)},
                        "data": [{
                            "lowSeries": {"data": rng(cols["low"])},
                            "openSeries": {"data": rng(cols["open"])},
                            "closeSeries": {"data": rng(cols["close"])},
                            "highSeries": {"data": rng(cols["high"])},
                        }],
                    },
                },
                "position": {"overlayPosition": anchor},
            }
        }
    }


def axis_range(df, cols):
    """데이터에 맞춘 세로축 범위(유효숫자 2자리로 정리). 0부터 시작하지 않게 하는 용도."""
    import math

    lo = min(df[c].min() for c in cols)
    hi = max(df[c].max() for c in cols)
    if lo == hi:
        return None
    span = hi - lo
    lo, hi = lo - span * 0.05, hi + span * 0.05

    def round_to(v, fn):
        if v == 0:
            return 0.0
        step = 10 ** (math.floor(math.log10(abs(v))) - 1)
        return fn(v / step) * step

    return round_to(lo, math.floor), round_to(hi, math.ceil)


def line_chart(title, sid, rows, cols, anchor, window=None):
    left = {"position": "LEFT_AXIS"}
    if window:
        left["viewWindowOptions"] = {"viewWindowMin": window[0], "viewWindowMax": window[1]}
    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "basicChart": {
                        "chartType": "LINE",
                        "legendPosition": "BOTTOM_LEGEND",
                        "headerCount": 1,
                        "axis": [{"position": "BOTTOM_AXIS"}, left],
                        "domains": [{"domain": col_range(sid, 0, rows)}],
                        "series": [
                            {"series": col_range(sid, c, rows), "targetAxis": "LEFT_AXIS"}
                            for c in cols
                        ],
                    },
                },
                "position": {"overlayPosition": anchor},
            }
        }
    }


def build_dashboard(api, data):
    ids = sheet_ids(api)
    if DASHBOARD in ids:  # 차트까지 통째로 지우고 다시 만든다
        api.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"deleteSheet": {"sheetId": ids[DASHBOARD]}}]},
        ).execute()
    api.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": DASHBOARD, "index": 0}}}]},
    ).execute()
    ids = sheet_ids(api)
    dash = ids[DASHBOARD]

    requests = []

    def anchor(row, col):
        return {
            "anchorCell": {"sheetId": dash,
                           "rowIndex": row * GRID_ROWS,
                           "columnIndex": col * GRID_COLS},
            "widthPixels": CHART_W,
            "heightPixels": CHART_H,
        }

    for row, items in enumerate(LAYOUT):
        for col, item in enumerate(items):
            if isinstance(item, str):  # 캔들
                if item not in data:
                    continue
                df = data[item]
                cols = {c: df.columns.get_loc(c) for c in df.columns}
                requests.append(
                    candle_chart(chart_title(item), ids[item], len(df), anchor(row, col), cols))
                continue
            name, cols = item  # 선 그래프
            if name not in data:
                continue
            df = data[name]
            used = [c for c in cols if c in df.columns]
            if not used:
                continue
            idxs = [df.columns.get_loc(c) for c in used]
            title = f"{TITLES.get((name, tuple(cols)), name)} {period_label(name)}"
            requests.append(
                line_chart(title, ids[name], len(df), idxs, anchor(row, col), axis_range(df, used)))

    api.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": requests}).execute()
    print(f"  dashboard: 차트 {len(requests)}개")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", action="store_true", help="데이터만 업로드")
    ap.add_argument("--charts", action="store_true", help="대시보드만 재생성")
    ap.add_argument("--ranges", action="store_true",
                    help="캔들차트 세로축에 넣을 최솟값/최댓값 출력 (수동 입력용)")
    args = ap.parse_args()

    if args.ranges:  # 캔들차트 축은 Sheets API가 지원하지 않아 UI에서 손으로 넣어야 한다
        for name in CANDLE:
            df = frames().get(name)
            if df is None:
                continue
            lo, hi = axis_range(df, ["low", "high"])
            print(f"{chart_title(name):26s} 최솟값 {lo:>12,.0f}  최댓값 {hi:>12,.0f}")
        return

    api = service()
    data = frames()
    if not args.charts:
        print("[데이터 업로드]")
        push_data(api, data)
        push_briefing(api)
    if not args.data:
        print("[대시보드 생성]")
        build_dashboard(api, data)
    print(f"완료: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")


if __name__ == "__main__":
    main()
