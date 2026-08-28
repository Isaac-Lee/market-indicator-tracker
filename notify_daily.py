#!/usr/bin/env python3
"""collect.py --daily 후 upload_sheets.py --data 실행하고 결과를 텔레그램으로 보낸다.

    python notify_daily.py

텔레그램 봇 토큰/채팅ID는 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 환경변수 또는
API-KEY.txt 의 `Telegram Bot Token:` / `Telegram Chat ID:` 줄에서 읽는다.
"""
import os
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

# 그룹 제목(Markdown bold): [(이모지+표시명, 계열, 열, 소수 자릿수), ...]
# 한 줄이 폰 화면 폭을 넘으면 뒤의 🟢/🔴만 다음 줄로 떨어져 읽기 사나워진다.
# 이름은 짧게 두고, 자릿수는 그 지표를 실제로 읽는 단위에 맞춘다 — 원화 종목에
# 소수점 두 자리는 아무 의미도 없으면서 여섯 글자를 잡아먹는다.
PCT = "pct"   # 금리처럼 값 자체가 %인 계열
BRIEFING_GROUPS = [
    ("지수", [
        ("🇰🇷 KOSPI", "kospi", "close", 2),
        ("🇰🇷 KOSDAQ", "kosdaq", "close", 2),
        ("🇺🇸 나스닥", "nasdaq", "close", 2),
    ]),
    ("종목", [
        ("📱 삼성전자", "samsung_elec", "close", 0),
        ("💾 하이닉스", "sk_hynix", "close", 0),
        ("🖥 엔비디아", "nvidia", "close", 2),
        ("☁️ 오라클", "oracle", "close", 2),
    ]),
    ("환율", [
        ("💵 원달러", "usdkrw", "close", 2),
        ("💴 달러엔", "usdjpy", "close", 2),
    ]),
    ("원자재·코인", [
        ("🥇 금", "gold", "close", 1),
        ("🛢 WTI", "wti", "close", 2),
        ("🪙 비트코인", "btc", "close", 0),
    ]),
    ("금리", [
        ("🇰🇷 국고채 3년", "ktb3y", "close", PCT),
        ("🇺🇸 미국채 10년", "ust10y", "close", PCT),
    ]),
]


def _item_line(label, name, col, digits, on):
    path = collect.DATA / f"{name}.csv"
    df = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
    cur, prev = collect.series_pair(df, col, on)
    if cur is None or prev is None:
        return f"{label} 미확인"
    diff = cur - prev
    pct = diff / prev * 100 if prev else 0.0
    unit, nd = ("%", 2) if digits is PCT else ("", digits)
    dot = "🟢" if diff >= 0 else "🔴"
    return f"{label} {cur:,.{nd}f}{unit} ({diff:+,.{nd}f}, {pct:+.2f}%) {dot}"


def build_briefing(on=None):
    """SPEC 계열 CSV에서 오늘자 스냅샷을 뽑아 텔레그램용 브리핑 문구를 만든다."""
    on = on or date.today()
    lines = [f"📊 {on.isoformat()} 시장 브리핑", ""]
    for title, items in BRIEFING_GROUPS:
        lines.append(f"▶ *{title}*")
        for label, name, col, digits in items:
            lines.append(_item_line(label, name, col, digits, on))
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
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY-RUN] 텔레그램 미전송\n{text}")
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
    # SKIP_KIS=1 이면 KIS 계열을 건너뛴다. 손으로 여러 번 돌려볼 때 KIS 알림톡이
    # 매번 오는 것을 막으려는 것이라, 예약 실행에서는 켜지 않는다.
    extra = ["--skip-kis"] if os.environ.get("SKIP_KIS") == "1" else []
    rc1, out1 = run("collect.py", "--daily", *extra)
    # DRY_RUN=1 이면 구글시트도 건드리지 않는다(빌드 테스트가 외부 상태를 바꾸면 안 됨).
    if os.environ.get("DRY_RUN") == "1":
        rc2, out2 = (0, "[DRY-RUN] 구글시트 업로드 건너뜀") if rc1 == 0 else (rc1, "collect 실패로 건너뜀")
    else:
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
