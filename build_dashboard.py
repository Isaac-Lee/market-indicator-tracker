#!/usr/bin/env python3
"""data/*.csv -> docs/data.json (GitHub Pages 정적 대시보드용 데이터).

    python build_dashboard.py
"""
import json
from pathlib import Path

import pandas as pd

import collect

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


def main():
    DOCS.mkdir(exist_ok=True)
    frames = collect.output_frames()
    series = {}
    for name, df in frames.items():
        df = df.copy()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        series[name] = json.loads(df.to_json(orient="records"))

    payload = {"generated": pd.Timestamp.now().isoformat(), "series": series}
    out_path = DOCS / "data.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"생성: {out_path} ({len(series)}개 계열)")


if __name__ == "__main__":
    main()
