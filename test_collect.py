"""python test_collect.py — 네트워크 없이 순수 로직만 검증."""
from datetime import date, timedelta

import pandas as pd

from collect import (PRICE_MAP, chunks, derive_investor, for_output, to_frame,
                     toss_frame, toss_investor_frame, wti_front_month)


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


def test_toss_frame():
    candles = [  # 토스 응답은 최신순, 값은 문자열
        {"timestamp": "2024-01-03T09:00:00+09:00", "openPrice": "2600", "highPrice": "2610",
         "lowPrice": "2590", "closePrice": "2605", "volume": "500"},
        {"timestamp": "2024-01-02T09:00:00+09:00", "openPrice": "2500", "highPrice": "2550",
         "lowPrice": "2490", "closePrice": "2540", "volume": "400"},
        {"timestamp": "2023-12-28T09:00:00+09:00", "closePrice": "2400"},  # start 이전 -> 잘림
    ]
    df = toss_frame(candles, date(2024, 1, 1))
    assert len(df) == 2 and list(df["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert df.iloc[1]["close"] == 2605 and df.iloc[0]["volume"] == 400
    assert df["date"].dt.tz is None  # tz 제거된 KST wall time
    assert toss_frame([], date(2024, 1, 1)).empty


def test_toss_investor_frame():
    def amt(buy, sell):
        return {"buyAmount": str(buy), "sellAmount": str(sell)}

    records = [{
        "date": "2024-01-02",
        "individual": amt(3e12, 2e12),
        "foreigner": amt(5e12, 4e12),
        "institution": {**amt(2e12, 3e12), "breakdown": {
            "pensionFund": amt(1e12, 0.5e12), "trust": amt(0.2e12, 0.3e12)}},
        "otherCorporation": amt(1e11, 1e11),
    }]
    df = toss_investor_frame(records, date(2024, 1, 1))
    assert df.iloc[0]["foreign"] == 1e6          # 1조원 순매수 -> 백만원 단위로 100만
    assert df.iloc[0]["institution"] == -1e6
    assert df.iloc[0]["pension"] == 5e5
    assert df.iloc[0]["trust"] == -1e5
    assert toss_investor_frame(records, date(2024, 2, 1)).empty  # start 이후만 남는다


def test_wti_front_month():
    assert wti_front_month(date(2025, 1, 5)) == "CLG25"   # 1월 -> 2월물(G)
    assert wti_front_month(date(2025, 12, 20)) == "CLF26"  # 12월 -> 익년 1월물(F)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
