#!/usr/bin/env python3
"""collect.py --daily 후 upload_sheets.py --data 실행하고 결과를 텔레그램으로 보낸다.

    python notify_daily.py

텔레그램 봇 토큰/채팅ID는 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 환경변수 또는
API-KEY.txt 의 `Telegram Bot Token:` / `Telegram Chat ID:` 줄에서 읽는다.
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

import collect
from kis_client import read_key

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

DASHBOARD_LINK = "https://buly.kr/2JqqPBg"   # GitHub Pages 대시보드(지표추적자)

# 그룹 제목(Markdown bold): [(이모지+표시명, 계열, 열, %단위 여부), ...]
BRIEFING_GROUPS = [
    ("지수", [
        ("🇰🇷 KOSPI", "kospi", "close", False),
        ("🇰🇷 KOSDAQ", "kosdaq", "close", False),
        ("🇺🇸 나스닥", "nasdaq", "close", False),
    ]),
    ("종목", [
        ("📱 삼성전자", "samsung_elec", "close", False),
        ("💾 SK하이닉스", "sk_hynix", "close", False),
        ("🖥 엔비디아", "nvidia", "close", False),
        ("☁️ 오라클", "oracle", "close", False),
    ]),
    ("환율", [
        ("💵 원달러", "usdkrw", "close", False),
        ("💴 달러엔", "usdjpy", "close", False),
    ]),
    ("금/원유", [
        ("🥇 금", "gold", "close", False),
        ("🛢 WTI", "wti", "close", False),
    ]),
    ("금리", [
        ("🇰🇷 국고채 3년", "ktb3y", "close", True),
        ("🇺🇸 미국채 10년", "ust10y", "close", True),
    ]),
]


def _item_line(label, name, col, is_pct, on):
    path = collect.DATA / f"{name}.csv"
    df = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
    cur, prev = collect.series_pair(df, col, on)
    if cur is None or prev is None:
        return f"{label} 미확인"
    diff = cur - prev
    pct = diff / prev * 100 if prev else 0.0
    unit = "%" if is_pct else ""
    dot = "🟢" if diff >= 0 else "🔴"
    return f"{label} {cur:,.2f}{unit} ({diff:+,.2f}, {pct:+.2f}%) {dot}"


def build_briefing(on=None):
    """SPEC 계열 CSV에서 오늘자 스냅샷을 뽑아 텔레그램용 브리핑 문구를 만든다."""
    on = on or date.today()
    lines = [f"📊 {on.isoformat()} 시장 브리핑", ""]
    for title, items in BRIEFING_GROUPS:
        lines.append(f"▶ *{title}*")
        for label, name, col, is_pct in items:
            lines.append(_item_line(label, name, col, is_pct, on))
        lines.append("")

    flow_path = collect.DATA / "investor_flow.csv"
    flow_df = pd.read_csv(flow_path, parse_dates=["date"]) if flow_path.exists() else None
    foreign, _ = collect.series_pair(flow_df, "foreign", on)
    institution, _ = collect.series_pair(flow_df, "institution", on)
    individual, _ = collect.series_pair(flow_df, "individual", on)
    lines.append("▶ *👥 수급(외국인/기관/개인)*")
    if None in (foreign, institution, individual):
        lines.append("미확인")
    else:
        lines.append(f"{foreign:+,.0f} / {institution:+,.0f} / {individual:+,.0f} (백만원)")

    lines.append("")
    lines.append("🔗 자세히보기(웹 페이지)")
    lines.append(DASHBOARD_LINK)
    return "\n".join(lines)


def run(*args):
    result = subprocess.run(
        [PYTHON, *args], cwd=ROOT, capture_output=True, text=True
    )
    output = result.stdout.strip() or result.stderr.strip()
    return result.returncode, output


def send_telegram(text):
    token = read_key(r"Telegram\s*Bot\s*Token", "TELEGRAM_BOT_TOKEN")
    chat_id = read_key(r"Telegram\s*Chat\s*ID", "TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("[건너뜀] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 없음", file=sys.stderr)
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )


def last_line(output):
    lines = [l for l in output.splitlines() if l.strip()]
    return lines[-1] if lines else "(출력 없음)"


def main():
    rc1, out1 = run("collect.py", "--daily")
    rc2, out2 = (run("upload_sheets.py", "--data") if rc1 == 0 else (rc1, "collect 실패로 건너뜀"))

    if rc1 == 0 and rc2 == 0:
        text = build_briefing()
    else:
        text = (
            "[지표추적자] 실패\n"
            f"collect.py rc={rc1}: {last_line(out1)}\n"
            f"upload_sheets.py rc={rc2}: {last_line(out2)}"
        )
    print(text)
    send_telegram(text)
    sys.exit(0 if rc1 == 0 and rc2 == 0 else 1)


if __name__ == "__main__":
    main()
