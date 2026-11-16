from datetime import datetime, timedelta, timezone

import pytest

from app.services.aqi import category, compute_index, sub_index, to_regulatory_units

END = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def hourly(value, n, unit="\u00b5g/m\u00b3", end=END):
    return [(end - timedelta(hours=i), value, unit) for i in range(n)]


@pytest.mark.parametrize("p,c,expected", [("pm25", 30, 50), ("pm25", 60, 100), ("pm25", 45, 75), ("pm25", 120, 300),
                                          ("pm25", 121, 301), ("pm25", 250, 400), ("pm25", 5000, 500),
                                          ("pm10", 50, 50), ("pm10", 100, 100), ("pm10", 430, 400)])
def test_sub_index_breakpoints(p, c, expected):
    assert round(sub_index(p, c)) == expected


def test_sub_index_rejects_bad_input():
    assert sub_index("pm25", -1) is None and sub_index("pm25", None) is None and sub_index("xyz", 10) is None


def test_categories():
    assert [category(i) for i in (0, 50, 51, 100, 150, 250, 350, 450)] == \
        ["Good", "Good", "Satisfactory", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]


def test_unit_conversions_and_unknown_units():
    assert to_regulatory_units("no2", 100, "ppb") == pytest.approx(188.16, abs=0.1)
    assert to_regulatory_units("co", 1000, "ppb") == pytest.approx(1.1457, abs=0.001)
    assert to_regulatory_units("o3", 50, "\u03bcg/m\u00b3") == 50          # Greek mu accepted
    assert to_regulatory_units("pm25", 40, "ppb") is None                 # wrong unit -> never guessed
    assert to_regulatory_units("no2", 5, "weird") is None


def test_overall_index_is_max_subindex():
    series = {"pm25": hourly(45, 24), "pm10": hourly(80, 24), "no2": hourly(20, 24, "ppb")}
    r = compute_index(series, END)
    assert r["valid"] and r["index"] == 80 and r["dominant_pollutant"] == "pm10" and r["category"] == "Satisfactory"
    assert r["official"] is False and r["sub_indices"]["pm25"]["sub_index"] == pytest.approx(74.7, abs=0.1)


def test_needs_enough_hours_and_three_pollutants():
    short = compute_index({"pm25": hourly(45, 10), "pm10": hourly(80, 24), "no2": hourly(20, 24, "ppb")}, END)
    assert "pm25" not in short["sub_indices"]                # only 10 of 24 hours -> excluded, never filled with zero
    assert short["valid"] is False and short["index"] is None  # now only 2 pollutants
    no_pm = compute_index({"no2": hourly(20, 24, "ppb"), "so2": hourly(5, 24, "ppb"), "co": hourly(500, 24, "ppb")}, END)
    assert no_pm["valid"] is False                           # CPCB needs PM2.5 or PM10


def test_o3_uses_max_8h_rolling_mean():
    pts = hourly(20, 24, end=END)
    pts = [(t, 120 if END - timedelta(hours=12) < t <= END - timedelta(hours=3) else v, u) for t, v, u in pts]
    r = compute_index({"o3": pts, "pm25": hourly(10, 24), "pm10": hourly(20, 24)}, END)
    assert r["sub_indices"]["o3"]["averaged_value"] == 120.0 and r["sub_indices"]["o3"]["averaging"] == "max 8h mean"
