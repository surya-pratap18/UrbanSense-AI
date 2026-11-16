"""Loads air-quality + weather rows from the database and turns them into per-station feature tables."""
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import select

import ml_engine._bootstrap  # noqa: F401
from app.models import Location, PollutionObservation, WeatherObservation
from ml_engine.preprocessing.air_quality import MET, POLL, add_targets, attach_weather, build_features, long_to_wide, regularize


def load_long(db, since: datetime | None = None) -> pd.DataFrame:
    q = select(PollutionObservation.location_id, PollutionObservation.observed_at, PollutionObservation.parameter,
               PollutionObservation.value).where(PollutionObservation.source == "openaq",
                                                 PollutionObservation.parameter.in_(POLL + MET),
                                                 PollutionObservation.data_origin == "OBSERVED")
    if since is not None:
        q = q.where(PollutionObservation.observed_at >= since)
    return pd.DataFrame(db.execute(q).all(), columns=["location_id", "observed_at", "parameter", "value"])


def load_weather(db, since: datetime | None = None) -> pd.DataFrame:
    q = select(WeatherObservation.valid_at, WeatherObservation.rainfall_mm, WeatherObservation.cloud_cover_pct,
               WeatherObservation.source).where(WeatherObservation.is_forecast.is_(False))
    if since is not None:
        q = q.where(WeatherObservation.valid_at >= since)
    df = pd.DataFrame(db.execute(q).all(), columns=["valid_at", "rainfall_mm", "cloud_cover_pct", "source"])
    if df.empty:
        return pd.DataFrame(columns=["rainfall_mm", "cloud_cover_pct"])
    df["valid_at"] = pd.to_datetime(df["valid_at"], utc=True)
    df["prio"] = (df["source"] == "open_meteo").astype(int)       # live API preferred over archive for the same hour
    df = df.sort_values(["valid_at", "prio"]).drop_duplicates("valid_at", keep="last").set_index("valid_at")
    return df[["rainfall_mm", "cloud_cover_pct"]]


def station_codes(db) -> dict[str, int]:
    ids = sorted(e for (e,) in db.execute(select(Location.external_id).where(Location.kind == "aq_station", Location.source == "openaq")))
    return {e: i for i, e in enumerate(ids)}


def station_tables(db, since: datetime | None = None) -> dict[str, pd.DataFrame]:
    """external_id -> regular hourly wide table (with weather attached)."""
    long = load_long(db, since)
    weather = load_weather(db, since - timedelta(days=2) if since else None)
    locs = {l.id: l.external_id for l in db.scalars(select(Location).where(Location.kind == "aq_station"))}
    out = {}
    for lid, grp in long.groupby("location_id"):
        w = regularize(long_to_wide(grp))
        if not w.empty:
            out[locs[lid]] = attach_weather(w, weather)
    return out


def training_frame(tables: dict[str, pd.DataFrame], codes: dict[str, int], targets, horizons) -> pd.DataFrame:
    parts = []
    for ext, w in tables.items():
        X = add_targets(build_features(w, codes[ext]), w, targets, horizons)
        X["station_key"] = ext
        parts.append(X)
    return pd.concat(parts).sort_index() if parts else pd.DataFrame()
