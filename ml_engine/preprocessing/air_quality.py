"""Feature engineering shared by TRAINING and PREDICTION (identical code path = no train/serve skew).
Every feature in row t uses only data observed at or before t (verified by tests)."""
import math

import numpy as np
import pandas as pd

POLL = ["pm25", "pm10", "no2", "so2", "co", "o3"]
MET = ["temperature", "relativehumidity", "wind_speed", "wind_direction"]
LAGS_BY = {"pm25": [0, 1, 2, 3, 6, 12, 24], "pm10": [0, 1, 2, 3, 6, 12, 24],
           "no2": [0, 3, 24], "so2": [0, 3, 24], "co": [0, 3, 24], "o3": [0, 3, 24]}
TZ = "Asia/Kolkata"


def long_to_wide(df_long: pd.DataFrame) -> pd.DataFrame:
    """One station: long rows (observed_at, parameter, value) -> wide table indexed by hour-end time (UTC)."""
    if df_long.empty:
        return pd.DataFrame(columns=POLL + MET)
    d = df_long.copy()
    d["observed_at"] = pd.to_datetime(d["observed_at"], utc=True)
    w = d.pivot_table(index="observed_at", columns="parameter", values="value", aggfunc="mean").sort_index()
    for c in POLL + MET:
        if c not in w:
            w[c] = np.nan
    return w[POLL + MET]


def regularize(w: pd.DataFrame) -> pd.DataFrame:
    """Force a regular hourly grid. Missing hours become NaN rows (never zero, never silently dropped)."""
    if w.empty:
        return w
    offset = int(pd.Series(w.index.minute).mode()[0])
    w = w[w.index.minute == offset]
    grid = pd.date_range(w.index.min(), w.index.max(), freq="1h", tz="UTC")
    out = w.reindex(grid)
    out.index.name = "t"
    return out


def attach_weather(w: pd.DataFrame, weather: pd.DataFrame | None) -> pd.DataFrame:
    """weather: hourly rows indexed by valid_at (UTC) with rainfall_mm, cloud_cover_pct. Uses only weather at/before t."""
    w = w.copy()
    cols = ["rainfall_mm", "rain_roll6", "rain_roll24", "cloud_cover_pct"]
    if weather is None or weather.empty:
        for c in cols:
            w[c] = np.nan
        return w
    wx = weather[~weather.index.duplicated(keep="last")].sort_index()[["rainfall_mm", "cloud_cover_pct"]].copy()
    wx = wx.reindex(pd.date_range(wx.index.min(), wx.index.max(), freq="1h", tz="UTC"))
    wx["rain_roll6"] = wx["rainfall_mm"].rolling(6, min_periods=3).sum()
    wx["rain_roll24"] = wx["rainfall_mm"].rolling(24, min_periods=12).sum()
    al = wx.reindex(w.index, method="ffill", tolerance=pd.Timedelta("2h"))
    for c in cols:
        w[c] = al[c].values
    return w


def build_features(w: pd.DataFrame, station_code: int) -> pd.DataFrame:
    X = {}
    for c, lags in LAGS_BY.items():
        for L in lags:
            X[f"{c}_lag{L}"] = w[c].shift(L)
    X["pm25_roll3"] = w["pm25"].rolling(3, min_periods=2).mean()
    X["pm25_roll6"] = w["pm25"].rolling(6, min_periods=3).mean()
    X["pm25_roll24"] = w["pm25"].rolling(24, min_periods=12).mean()
    X["pm10_roll6"] = w["pm10"].rolling(6, min_periods=3).mean()
    X["pm10_roll24"] = w["pm10"].rolling(24, min_periods=12).mean()
    X["pm25_diff1"] = w["pm25"] - w["pm25"].shift(1)
    X["temperature"] = w["temperature"]
    X["relativehumidity"] = w["relativehumidity"]
    X["wind_speed"] = w["wind_speed"]
    X["wind_speed_roll3"] = w["wind_speed"].rolling(3, min_periods=2).mean()
    rad = np.deg2rad(w["wind_direction"])
    X["wind_dir_sin"], X["wind_dir_cos"] = np.sin(rad), np.cos(rad)
    for c in ["rainfall_mm", "rain_roll6", "rain_roll24", "cloud_cover_pct"]:
        X[c] = w[c] if c in w else np.nan
    lt = w.index.tz_convert(TZ)
    X["hour_sin"], X["hour_cos"] = np.sin(2 * math.pi * lt.hour / 24), np.cos(2 * math.pi * lt.hour / 24)
    X["dow"], X["is_weekend"], X["month"] = lt.dayofweek, (lt.dayofweek >= 5).astype(int), lt.month
    X["station_code"] = station_code
    return pd.DataFrame(X, index=w.index)


def add_targets(X: pd.DataFrame, w: pd.DataFrame, targets=("pm25", "pm10"), horizons=(1, 3, 6)) -> pd.DataFrame:
    X = X.copy()
    for t in targets:
        for h in horizons:
            X[f"y_{t}_h{h}"] = w[t].shift(-h)      # the future value we want to predict (never used as a feature)
    return X
