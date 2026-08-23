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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
