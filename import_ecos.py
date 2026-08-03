#!/usr/bin/env python3
"""ECOS '시장금리(일별)' 가로형 엑셀을 data/ktb3y.csv 로 변환.

    python import_ecos.py "시장금리(일별)_04000531.xlsx"

ECOS 파일 구조: 1행 = 헤더(6열째부터 날짜), 2행부터 = 계정항목별 값.
openpyxl 이 ECOS 파일 스타일을 못 읽는 경우가 있어 xlsx(zip+xml)를 직접 파싱한다.
"""
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def read_sheet(path, sheet="xl/worksheets/sheet1.xml"):
    """xlsx 첫 시트를 2차원 리스트로 반환."""
    zf = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in zf.namelist():
        raw = zf.read("xl/sharedStrings.xml").decode()
        shared = [
            "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))
            for si in re.findall(r"<si>(.*?)</si>", raw, re.S)
        ]

    def value(cell):
        typ = re.search(r't="(\w+)"', cell)
        val = re.search(r"<v>(.*?)</v>", cell, re.S)
        if not val:
            inline = re.search(r"<is>.*?<t[^>]*>(.*?)</t>", cell, re.S)
            return inline.group(1) if inline else ""
        if typ and typ.group(1) == "s":
            return shared[int(val.group(1))]
        return val.group(1)

    sheet_xml = zf.read(sheet).decode()
    return [
        [value(c) for c in re.findall(r"<c .*?(?:/>|</c>)", row, re.S)]
        for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet_xml, re.S)
    ]


def to_series(rows, want="국고채(3년)"):
    header = rows[0]
    date_cols = [(i, v) for i, v in enumerate(header) if re.fullmatch(r"\d{4}/\d{2}/\d{2}", v or "")]
    if not date_cols:
        sys.exit("날짜 헤더를 찾지 못했다. ECOS '가로형(시점=열)' 로 받은 파일인지 확인할 것")
    for row in rows[1:]:
        if any(want in (cell or "") for cell in row[:5]):
            recs = [(d, row[i]) for i, d in date_cols if i < len(row) and row[i] not in ("", None)]
            df = pd.DataFrame(recs, columns=["date", "close"])
            df["date"] = pd.to_datetime(df["date"], format="%Y/%m/%d")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            return df.dropna().sort_values("date")
    sys.exit(f"'{want}' 계정항목이 파일에 없다. 받은 항목: "
             f"{[r[2] for r in rows[1:] if len(r) > 2]}")


def read_any(path):
    """ECOS 다운로드 파일(xlsx / csv)을 2차원 리스트로."""
    if path.suffix.lower() == ".csv":
        import csv

        with open(path, encoding="utf-8-sig", newline="") as fh:
            return list(csv.reader(fh))
    return read_sheet(path)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    df = to_series(read_any(src))
    DATA.mkdir(exist_ok=True)
    out = DATA / "ktb3y.csv"
    if out.exists():
        old = pd.read_csv(out, parse_dates=["date"])
        df = pd.concat([old, df]).drop_duplicates("date", keep="last").sort_values("date")
    df.to_csv(out, index=False, date_format="%Y-%m-%d")
    print(f"{out}: {len(df)}행 ({df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}), "
          f"단위 연%, 최근값 {df['close'].iloc[-1]}")


if __name__ == "__main__":
    main()
