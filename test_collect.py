"""python test_collect.py — 네트워크 없이 순수 로직만 검증."""
from datetime import date, timedelta

import pandas as pd

from collect import (PRICE_MAP, chunks, derive_investor, for_output, to_frame,
                     wti_front_month)


def test_chunks():
    got = list(chunks(date(2024, 1, 1), date(2024, 5, 1), days=100))
    assert got[0] == (date(2024, 1, 1), date(2024, 4, 9)), got
    assert got[-1][1] == date(2024, 5, 1)
    assert list(chunks(date(2024, 1, 1), date(2024, 1, 1))) == [(date(2024, 1, 1), date(2024, 1, 1))]


def test_to_frame_normalizes_and_dedupes():
    rows = [
        {"stck_bsop_date": "20240102", "stck_oprc": "100", "stck_hgpr": "110",
         "stck_lwpr": "90", "stck_clpr": "105", "acml_vol": "1000"},
        {"stck_bsop_date": "20240102", "stck_clpr": "106"},          # 중복 날짜
        {"bstp_nmix_prpr": "2500"},                                   # 날짜 없음 -> 버림
        {"stck_bsop_date": "20240103", "ovrs_nmix_prpr": "2600"},     # 다른 필드명
    ]
    df = to_frame(rows, PRICE_MAP)
    assert len(df) == 2, df
    assert df.iloc[0]["close"] == 105  # keep='first' 아님: drop_duplicates 기본 first
    assert df.iloc[1]["close"] == 2600
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_derive_investor():
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-05", periods=10, freq="W-FRI"),
        "foreign": [100] * 10,
        "institution": [-50] * 10,
    })
    out = derive_investor(df)
    assert out["foreign_cum"].iloc[-1] == 1000
    assert out["institution_cum"].iloc[-1] == -500
    assert out["foreign_ma4w"].iloc[-1] == 100         # 주간 4행 이동평균
    assert pd.isna(out["foreign_ma4w"].iloc[2])        # 4주 미만 구간은 NaN
    assert out["foreign_cum_ma4w"].iloc[-1] == 850     # (700+800+900+1000)/4


def test_for_output_weekly_and_trim():
    days = pd.date_range("2024-01-01", periods=800, freq="D")
    today = days[-1].date()
    daily = pd.DataFrame({"date": days, "foreign": 1, "institution": 2,
                          "individual": 3, "pension": 4, "trust": 5, "close": range(800)})
    out = for_output("investor_flow", daily, today=today)
    assert (out["date"].diff().dropna() == pd.Timedelta("7D")).all()   # 주간으로 묶임
    assert out["date"].min() >= pd.Timestamp(today - timedelta(days=730))  # 2년으로 잘림
    assert out["foreign"].iloc[1] == 7          # 주간 합계
    assert out["close"].iloc[1] == daily.set_index("date").loc[out["date"].iloc[1], "close"]
    assert "foreign_cum" in out

    ohlc = pd.DataFrame({"date": days, "open": 1.0, "high": 2.0, "low": 0.5,
                         "close": 1.5, "volume": 10})
    trimmed = for_output("kospi", ohlc, today=today)
    assert len(trimmed) == 184 and trimmed["date"].max() == pd.Timestamp(today)  # 6개월 일별


def test_wti_front_month():
    assert wti_front_month(date(2025, 1, 5)) == "CLG25"   # 1월 -> 2월물(G)
    assert wti_front_month(date(2025, 12, 20)) == "CLF26"  # 12월 -> 익년 1월물(F)


def test_yahoo_series_covers_every_yahoo_backed_spec():
    """SPEC에 있는 야후 계열은 전부 YAHOO_SERIES에 심볼이 있어야 한다."""
    from collect import SPEC, YAHOO_SERIES
    for name in ("wti", "sp500", "nasdaq", "dow", "russell2000", "dxy", "btc", "gold"):
        assert name in SPEC, f"SPEC에 {name} 없음"
        assert name in YAHOO_SERIES, f"YAHOO_SERIES에 {name} 없음"
    assert YAHOO_SERIES["sp500"] == "^GSPC"
    assert YAHOO_SERIES["wti"] == "CL=F"


def test_fred_series_and_spec_are_daily():
    """미국채는 일별로 저장한다. 주간 리샘플은 출력 시점(for_output)의 일이다."""
    from collect import FRED_SERIES, SPEC
    assert FRED_SERIES == {"ust10y": "DGS10", "ust2y": "DGS2"}, FRED_SERIES
    assert "ust10y_weekly" not in SPEC, "옛 이름이 남아 있다"
    for name in ("ust10y", "ust2y"):
        assert SPEC[name][1] == "D", f"{name} 저장 주기가 일별이 아니다"


def test_bond_codes_cover_both_maturities():
    """국고 3년·10년이 같은 ECOS 통계표의 다른 항목 코드로 잡혀 있어야 한다."""
    import json
    from pathlib import Path
    from collect import SPEC
    codes = json.loads((Path(__file__).parent / "codes" / "instruments.json").read_text())
    assert codes["bond"]["ktb3y"]["ecos_item"] == "010200000"
    assert codes["bond"]["ktb10y"]["ecos_item"] == "010210000"
    assert codes["bond"]["ktb10y"]["ecos_stat"] == codes["bond"]["ktb3y"]["ecos_stat"]
    assert SPEC["ktb10y"] == SPEC["ktb3y"], "두 만기의 기간·주기가 달라선 안 된다"


def test_stale_series_boundary():
    """5일은 정상, 6일은 stale. 주말 2일 + 연휴 3일까지 흡수하는 임계다."""
    from collect import stale_series
    today = date(2026, 8, 24)
    last = {
        "kospi": today,                        # 당일
        "dxy": today - timedelta(days=5),      # 경계: 정상
        "ktb10y": today - timedelta(days=6),   # 경계 밖: stale
        "gold": None,                          # 한 번도 수집된 적 없음
    }
    got = stale_series(last, today)
    assert [n for n, _ in got] == ["gold", "ktb10y"], got   # 이름순
    assert dict(got)["gold"] is None


def test_summary_line_shapes():
    from collect import summary_line
    assert summary_line(19, []) == "19계열 갱신 · stale 0"
    assert summary_line(19, [("ktb10y", date(2026, 8, 14))]) == \
        "19계열 갱신 · stale 1 (ktb10y 마지막 08-14)"
    assert summary_line(19, [("dxy", None), ("ktb10y", date(2026, 8, 14))]) == \
        "19계열 갱신 · stale 2 (dxy 마지막 없음, ktb10y 마지막 08-14)"


def test_summary_line_is_one_line():
    """다이제스트가 stdout 마지막 '줄'을 가져가므로 개행이 들어가면 안 된다."""
    from collect import summary_line
    many = [(f"s{i}", date(2026, 8, 1)) for i in range(19)]
    assert "\n" not in summary_line(19, many)


def test_snapshot_tables_match_claude_md():
    """항목 수와 순서가 CLAUDE.md의 나열과 같아야 한다."""
    from collect import SNAPSHOT_KR, SNAPSHOT_US
    assert len(SNAPSHOT_KR) == 11, len(SNAPSHOT_KR)
    assert len(SNAPSHOT_US) == 13, len(SNAPSHOT_US)   # 오라클·엔비디아 추가분 포함
    assert [l for l, _, _ in SNAPSHOT_KR][:2] == ["KOSPI", "KOSDAQ"]
    assert [l for l, _, _ in SNAPSHOT_US][:4] == ["S&P 500", "나스닥", "다우", "러셀 2000"]
    # Fear & Greed는 수집하지 않으므로 계열 이름이 비어 있다
    assert dict((l, n) for l, n, _ in SNAPSHOT_US)["Fear & Greed"] == ""
    # 수집 대상 계열은 전부 SPEC에 있어야 한다
    from collect import SPEC
    for _, name, _ in SNAPSHOT_KR + SNAPSHOT_US:
        assert name == "" or name in SPEC, name


def test_series_pair_picks_the_row_on_or_before_the_date():
    from collect import series_pair
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21"]),
        "close": [1.0, 2.0, 3.0],
    })
    assert series_pair(df, "close", date(2026, 8, 21)) == (3.0, 2.0)
    assert series_pair(df, "close", date(2026, 8, 23)) == (3.0, 2.0)   # 휴장일 조회
    assert series_pair(df, "close", date(2026, 8, 19)) == (1.0, None)  # 직전 행 없음
    assert series_pair(df, "close", date(2026, 8, 1)) == (None, None)  # 데이터 이전
    assert series_pair(None, "close", date(2026, 8, 21)) == (None, None)


def test_snapshot_row_marks_missing_and_flow_columns():
    from collect import snapshot_row
    # 못 구한 값은 미확인, 빈칸 금지
    assert snapshot_row("Fear & Greed", "", None, None) == \
        "| Fear & Greed | 미확인 | 미확인 | 미확인 |"
    # 직전 값이 없으면 변동만 미확인
    assert snapshot_row("KOSPI", "kospi", 6912.95, None) == \
        "| KOSPI | 6,912.95 | 미확인 | 미확인 |"
    # 정상 행
    assert snapshot_row("KOSPI", "kospi", 6912.95, 6852.58) == \
        "| KOSPI | 6,912.95 | +60.37 | +0.88% |"
    # 금리는 소수 3자리
    assert snapshot_row("국고채 10년", "ktb10y", 4.376, 4.323) == \
        "| 국고채 10년 | 4.376 | +0.053 | +1.23% |"
    # 수급은 순매수 자체가 흐름이라 변동 열이 해석되지 않는다 -> 미확인이 아니라 —
    assert snapshot_row("수급 외국인(백만원)", "investor_flow", -558024.0, 2266504.0) == \
        "| 수급 외국인(백만원) | -558,024 | — | — |"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
