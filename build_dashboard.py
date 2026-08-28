#!/usr/bin/env python3
"""data/*.csv -> docs/data.json (GitHub Pages 정적 대시보드용 데이터).

    python build_dashboard.py
"""
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import collect

KST = ZoneInfo("Asia/Seoul")

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def main():
    DOCS.mkdir(exist_ok=True)
    # trim=False: 이동평균·일목 같은 보조지표가 앞쪽 데이터를 먹으므로 쌓인 것을 전부 넘긴다.
    frames = collect.output_frames(trim=False)
    series = {}
    for name, df in frames.items():
        df = df.copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        series[name] = json.loads(df.to_json(orient="records"))

    payload = {"generated": pd.Timestamp.now(tz=KST).isoformat(), "series": series}
    out_path = DOCS / "data.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"생성: {out_path} ({len(series)}개 계열)")


if __name__ == "__main__":
    main()
