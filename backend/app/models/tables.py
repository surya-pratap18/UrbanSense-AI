"""All 17 tables. All timestamps are stored in UTC (convert to Asia/Kolkata only for display).

data_origin values (never mix them up in the UI):
  OBSERVED   measured by a real sensor / API
  SIMULATED  generated demonstration data
  BENCHMARK  public benchmark dataset from another region (e.g. PEMS-BAY), never shown as Bhubaneswar truth
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)

from app.database.base import Base


def _now():
    return datetime.now(timezone.utc)


def TS(**kw):
    return Column(DateTime(timezone=True), **kw)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(120), default="")
    role = Column(String(20), nullable=False, default="user")  # user | admin
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = TS(default=_now, nullable=False)


class City(Base):
    __tablename__ = "cities"
    id = Column(Integer, primary_key=True)
    slug = Column(String(60), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    state = Column(String(120))
    country = Column(String(80), default="India")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    timezone = Column(String(60), default="Asia/Kolkata")
    created_at = TS(default=_now)


class Ward(Base):
    __tablename__ = "wards"
    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)
    ward_no = Column(String(20), nullable=False)
    name = Column(String(160))
    centroid_lat = Column(Float)
    centroid_lon = Column(Float)
    population = Column(Integer)
    area_sqkm = Column(Float)
    geometry_geojson = Column(Text)  # polygon, if available
    data_origin = Column(String(12), default="OBSERVED")
    __table_args__ = (UniqueConstraint("city_id", "ward_no", name="uq_ward_city_no"),)


class Location(Base):
    """Generic point: air-quality station, weather point, etc."""
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)
    ward_id = Column(Integer, ForeignKey("wards.id"))
    kind = Column(String(30), nullable=False)  # aq_station | weather_point | other
    name = Column(String(200), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    source = Column(String(40))           # e.g. openaq, cpcb
    external_id = Column(String(80))      # id used by the source
    created_at = TS(default=_now)
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_location_source_ext"),)


class RoadSegment(Base):
    """A monitored road point/segment (TomTom flow-segment query point)."""
    __tablename__ = "road_segments"
    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)
    ward_id = Column(Integer, ForeignKey("wards.id"))
    name = Column(String(200), nullable=False)
    road_type = Column(String(40))  # trunk | primary | secondary | ... (OSM highway tag)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry_geojson = Column(Text)
    osm_way_id = Column(String(30))
    is_active = Column(Boolean, default=True)
    created_at = TS(default=_now)


class TrafficObservation(Base):
    __tablename__ = "traffic_observations"
    id = Column(Integer, primary_key=True)
    segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=False)
    observed_at = TS(nullable=False)
    fetched_at = TS(default=_now)
    current_speed_kmh = Column(Float)
    free_flow_speed_kmh = Column(Float)
    congestion_ratio = Column(Float)      # current / free-flow (1.0 = free flowing)
    current_travel_time_s = Column(Float)
    confidence = Column(Float)            # provider confidence, if given
    road_closure = Column(Boolean)
    source = Column(String(40), nullable=False)
    data_origin = Column(String(12), nullable=False, default="OBSERVED")
    __table_args__ = (UniqueConstraint("segment_id", "observed_at", "source", name="uq_traffic_obs"),
                      Index("ix_traffic_seg_time", "segment_id", "observed_at"))


class TrafficPrediction(Base):
    __tablename__ = "traffic_predictions"
    id = Column(Integer, primary_key=True)
    segment_id = Column(Integer, ForeignKey("road_segments.id"), nullable=False)
    made_at = TS(nullable=False)
    target_time = TS(nullable=False)
    horizon_min = Column(Integer, nullable=False)
    predicted_ratio = Column(Float)
    predicted_speed_kmh = Column(Float)
    congestion_level = Column(String(20))
    lower = Column(Float)
    upper = Column(Float)
    model_version = Column(String(60))
    calibration_status = Column(String(30))  # LOCALLY_VALIDATED | TRANSFERRED_UNCALIBRATED | BASELINE_ONLY
    __table_args__ = (UniqueConstraint("segment_id", "made_at", "horizon_min", name="uq_traffic_pred"),
                      Index("ix_traffic_pred_seg_target", "segment_id", "target_time"))


class PollutionObservation(Base):
    """Long format: one row per station + pollutant + time. Missing values are simply absent rows (never zero)."""
    __tablename__ = "pollution_observations"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    observed_at = TS(nullable=False)
    fetched_at = TS(default=_now)
    parameter = Column(String(20), nullable=False)  # pm25 pm10 no2 so2 co o3 ...
    value = Column(Float, nullable=False)
    unit = Column(String(20))
    source = Column(String(40), nullable=False)
    license = Column(String(120))
    data_origin = Column(String(12), nullable=False, default="OBSERVED")
    __table_args__ = (UniqueConstraint("location_id", "observed_at", "parameter", "source", name="uq_pollution_obs"),
                      Index("ix_poll_loc_param_time", "location_id", "parameter", "observed_at"))


class PollutionPrediction(Base):
    __tablename__ = "pollution_predictions"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    made_at = TS(nullable=False)
    target_time = TS(nullable=False)
    horizon_h = Column(Integer, nullable=False)
    parameter = Column(String(20), nullable=False)
    predicted_value = Column(Float)
    lower = Column(Float)
    upper = Column(Float)
    trend = Column(String(12))  # rising | falling | stable
    index_category = Column(String(30))  # CPCB-style indicative category
    model_version = Column(String(60))
    __table_args__ = (UniqueConstraint("location_id", "made_at", "horizon_h", "parameter", name="uq_pollution_pred"),)


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    valid_at = TS(nullable=False)         # time the values describe
    fetched_at = TS(default=_now)
    is_forecast = Column(Boolean, default=False, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    temperature_c = Column(Float)
    humidity_pct = Column(Float)
    rainfall_mm = Column(Float)
    wind_speed_kmh = Column(Float)
    wind_direction_deg = Column(Float)
    cloud_cover_pct = Column(Float)
    weather_code = Column(Integer)
    source = Column(String(40), default="open_meteo")
    __table_args__ = (UniqueConstraint("city_id", "valid_at", "is_forecast", "source", name="uq_weather"),
                      Index("ix_weather_city_time", "city_id", "valid_at"))


class WasteRecord(Base):
    __tablename__ = "waste_records"
    id = Column(Integer, primary_key=True)
    ward_id = Column(Integer, ForeignKey("wards.id"), nullable=False)
    record_date = Column(DateTime, nullable=False)  # date (stored as midnight)
    population = Column(Integer)
    waste_kg = Column(Float, nullable=False)
    category = Column(String(40), default="mixed")
    collection_capacity_kg = Column(Float)
    collection_frequency_per_day = Column(Float)
    is_holiday = Column(Boolean, default=False)
    weather_condition = Column(String(40))
    data_origin = Column(String(12), nullable=False, default="SIMULATED")
    created_at = TS(default=_now)
    __table_args__ = (UniqueConstraint("ward_id", "record_date", "category", "data_origin", name="uq_waste_rec"),
                      Index("ix_waste_ward_date", "ward_id", "record_date"))


class WastePrediction(Base):
    __tablename__ = "waste_predictions"
    id = Column(Integer, primary_key=True)
    ward_id = Column(Integer, ForeignKey("wards.id"), nullable=False)
    made_at = TS(nullable=False)
    target_date = Column(DateTime, nullable=False)
    predicted_kg = Column(Float)
    capacity_gap_kg = Column(Float)       # predicted - capacity (positive = shortfall)
    priority = Column(String(12))
    model_version = Column(String(60))
    trained_on = Column(String(12), default="SIMULATED")  # honesty flag: what kind of data trained the model
    __table_args__ = (UniqueConstraint("ward_id", "made_at", "target_date", name="uq_waste_pred"),)


class HotspotCluster(Base):
    __tablename__ = "hotspot_clusters"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)  # traffic | pollution | waste  (never mixed)
    run_at = TS(nullable=False, default=_now)
    method = Column(String(30))                # dbscan | ranking
    cluster_label = Column(Integer)
    centroid_lat = Column(Float)
    centroid_lon = Column(Float)
    radius_m = Column(Float)
    n_points = Column(Integer)
    severity = Column(Float)
    ward_id = Column(Integer, ForeignKey("wards.id"))
    params = Column(JSON)
    members = Column(JSON)
    __table_args__ = (Index("ix_hotspot_kind_run", "kind", "run_at"),)


class ResourceRecommendation(Base):
    __tablename__ = "resource_recommendations"
    id = Column(Integer, primary_key=True)
    created_at = TS(default=_now, nullable=False)
    kind = Column(String(20), nullable=False)  # waste | traffic | pollution
    method = Column(String(30))                # rule_based | ortools
    target_type = Column(String(20))           # ward | road_segment | station
    target_id = Column(Integer)
    target_name = Column(String(200))
    rank = Column(Integer)
    priority_score = Column(Float)
    allocated_units = Column(Float)
    reason = Column(Text)                      # human-readable explanation
    details = Column(JSON)
    is_simulated_input = Column(Boolean, default=False)
    disclaimer = Column(String(200), default="Planning suggestion only. Not an official government decision or emergency alert.")


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    created_at = TS(default=_now, nullable=False)
    kind = Column(String(20), nullable=False)
    severity = Column(String(12), nullable=False)  # info | warning | high
    message = Column(Text, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"))
    segment_id = Column(Integer, ForeignKey("road_segments.id"))
    ward_id = Column(Integer, ForeignKey("wards.id"))
    is_active = Column(Boolean, default=True)
    data_origin = Column(String(12), default="OBSERVED")


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    id = Column(Integer, primary_key=True)
    module = Column(String(20), nullable=False)       # traffic | pollution | waste
    name = Column(String(60), nullable=False)         # e.g. xgboost_ratio_h15
    version = Column(String(40), nullable=False)
    dataset_version = Column(String(80))
    trained_at = TS(nullable=False, default=_now)
    feature_schema = Column(JSON)
    metrics = Column(JSON)                            # real held-out test metrics only
    baseline_metrics = Column(JSON)
    artifact_path = Column(String(300))
    calibration_status = Column(String(30))
    trained_on = Column(String(12))                   # OBSERVED | SIMULATED | BENCHMARK
    is_active = Column(Boolean, default=False)
    notes = Column(Text)
    __table_args__ = (UniqueConstraint("module", "name", "version", name="uq_model_version"),)


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"
    id = Column(Integer, primary_key=True)
    source_key = Column(String(40), unique=True, nullable=False)
    display_name = Column(String(120))
    expected_interval_min = Column(Float)
    last_attempt_at = TS()
    last_success_at = TS()
    last_error = Column(Text)
    consecutive_failures = Column(Integer, default=0)
    records_last_run = Column(Integer, default=0)
    attribution = Column(String(300))
    license_url = Column(String(300))
