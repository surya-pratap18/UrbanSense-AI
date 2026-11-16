"""CPCB-style indicative air-quality index (India National AQI, CPCB 2014).

IMPORTANT: this is an INDICATIVE index, not an official AQI.
 - PM2.5, PM10, NO2, SO2: 24-hour average (needs >= 16 of the last 24 hourly values)
 - O3, CO: maximum 8-hour rolling average within the last 24 h (each average needs >= 6 of 8 hours)
 - Overall index = highest sub-index, valid only with >= 3 pollutants incl. PM2.5 or PM10
 - Units: ug/m3 for all except CO (mg/m3). OpenAQ reports gases in ppb, converted at 25 C, 1 atm (approximate).
Breakpoints: PM2.5/PM10 bands verified against CPCB tables; NO2/SO2/O3/CO upper bands should be re-checked
against the official CPCB PDF before the final report. The 'Severe' band has no official upper limit; here the
index reaches 500 at 1.5x the top of the 'Very Poor' band (documented approximation)."""
from datetime import datetime, timedelta

from app.core.datastate import as_utc

# (conc_low, conc_high, index_low, index_high)
BANDS = {
    "pm25": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300), (121, 250, 301, 400), (251, 375, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200), (251, 350, 201, 300), (351, 430, 301, 400), (431, 645, 401, 500)],
    "no2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200), (181, 280, 201, 300), (281, 400, 301, 400), (401, 600, 401, 500)],
    "o3": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 168, 101, 200), (169, 208, 201, 300), (209, 748, 301, 400), (749, 1122, 401, 500)],
    "co": [(0, 1.0, 0, 50), (1.1, 2.0, 51, 100), (2.1, 10, 101, 200), (10.1, 17, 201, 300), (17.1, 34, 301, 400), (34.1, 51, 401, 500)],
    "so2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200), (381, 800, 201, 300), (801, 1600, 301, 400), (1601, 2400, 401, 500)],
}
WINDOWS = {"pm25": (24, 16), "pm10": (24, 16), "no2": (24, 16), "so2": (24, 16), "o3": (8, 6), "co": (8, 6)}  # (hours, min count)
MOLAR_VOLUME = 24.45  # L/mol at 25 C, 1 atm
MW = {"no2": 46.0055, "so2": 64.066, "o3": 47.9982, "co": 28.0101}
UG = {"\u00b5g/m\u00b3", "ug/m3", "\u00b5g/m3", "ug/m\u00b3"}
CATEGORIES = [(50, "Good"), (100, "Satisfactory"), (200, "Moderate"), (300, "Poor"), (400, "Very Poor"), (500, "Severe")]


def category(index: float | None) -> str | None:
    if index is None:
        return None
    for top, name in CATEGORIES:
        if index <= top:
            return name
    return "Severe"


def sub_index(param: str, conc: float | None) -> float | None:
    bands = BANDS.get(param)
    if bands is None or conc is None or conc < 0:
        return None
    for c_lo, c_hi, i_lo, i_hi in bands:
        if conc <= c_hi:
            c = max(conc, c_lo)  # values falling in the small gap between bands (e.g. 30.5) take the lower edge
            return i_lo + (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo)
    return 500.0


def _norm_unit(unit: str | None) -> str:
    return (unit or "").lower().replace("\u03bc", "\u00b5").replace(" ", "")


def to_regulatory_units(param: str, value: float, unit: str | None) -> float | None:
    """Convert to ug/m3 (CO: mg/m3). Returns None if the unit is unknown (never guess)."""
    u = _norm_unit(unit)
    if param in ("pm25", "pm10"):
        return value if u in UG else None
    if param == "co":
        if u == "ppb":
            return value * MW["co"] / MOLAR_VOLUME / 1000
        if u == "ppm":
            return value * MW["co"] / MOLAR_VOLUME
        if u in ("mg/m3", "mg/m\u00b3"):
            return value
        return value / 1000 if u in UG else None
    if param in ("no2", "so2", "o3"):
        if u == "ppb":
            return value * MW[param] / MOLAR_VOLUME
        if u == "ppm":
            return value * 1000 * MW[param] / MOLAR_VOLUME
        return value if u in UG else None
    return None


def _window_mean(vals: dict, end: datetime, hours: int, min_count: int) -> float | None:
    lo = end - timedelta(hours=hours)
    xs = [v for t, v in vals.items() if lo < t <= end]
    return sum(xs) / len(xs) if len(xs) >= min_count else None


def compute_index(series: dict[str, list[tuple[datetime, float, str]]], at: datetime) -> dict:
    """series: parameter -> [(hour_end_timestamp, value, unit)]. Missing hours are simply absent (never zero)."""
    at = as_utc(at)
    subs = {}
    for param, points in series.items():
        if param not in BANDS:
            continue
        hours, min_count = WINDOWS[param]
        vals = {}
        for ts, v, unit in points:
            conv = to_regulatory_units(param, v, unit)
            if conv is not None and conv >= 0:
                vals[as_utc(ts)] = conv
        if hours == 24:
            avg, label = _window_mean(vals, at, 24, min_count), "24h mean"
        else:  # max of the rolling 8h means over the last 24 h
            cands = [m for k in range(24) if (m := _window_mean(vals, at - timedelta(hours=k), 8, min_count)) is not None]
            avg, label = (max(cands) if cands else None), "max 8h mean"
        if avg is None:
            continue
        si = sub_index(param, avg)
        subs[param] = {"averaged_value": round(avg, 2), "unit": "mg/m\u00b3" if param == "co" else "\u00b5g/m\u00b3",
                       "averaging": label, "sub_index": round(si, 1)}
    out = {"index": None, "category": None, "dominant_pollutant": None, "sub_indices": subs,
           "pollutants_used": len(subs), "valid": False, "official": False, "reason": None}
    if len(subs) < 3 or not ({"pm25", "pm10"} & set(subs)):
        out["reason"] = "Insufficient data: CPCB method needs at least 3 pollutants including PM2.5 or PM10 with enough hourly coverage."
        return out
    dom = max(subs, key=lambda p: subs[p]["sub_index"])
    out.update(index=int(round(subs[dom]["sub_index"])), dominant_pollutant=dom, valid=True)
    out["category"] = category(out["index"])
    return out
