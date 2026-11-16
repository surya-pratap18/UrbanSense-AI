-- UrbanSense AI: PostgreSQL schema (generated from SQLAlchemy models)

CREATE TABLE cities (
	id SERIAL NOT NULL, 
	slug VARCHAR(60) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	state VARCHAR(120), 
	country VARCHAR(80), 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	timezone VARCHAR(60), 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
);

CREATE TABLE data_source_status (
	id SERIAL NOT NULL, 
	source_key VARCHAR(40) NOT NULL, 
	display_name VARCHAR(120), 
	expected_interval_min FLOAT, 
	last_attempt_at TIMESTAMP WITH TIME ZONE, 
	last_success_at TIMESTAMP WITH TIME ZONE, 
	last_error TEXT, 
	consecutive_failures INTEGER, 
	records_last_run INTEGER, 
	attribution VARCHAR(300), 
	license_url VARCHAR(300), 
	PRIMARY KEY (id), 
	UNIQUE (source_key)
);

CREATE TABLE model_registry (
	id SERIAL NOT NULL, 
	module VARCHAR(20) NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	dataset_version VARCHAR(80), 
	trained_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	feature_schema JSON, 
	metrics JSON, 
	baseline_metrics JSON, 
	artifact_path VARCHAR(300), 
	calibration_status VARCHAR(30), 
	trained_on VARCHAR(12), 
	is_active BOOLEAN, 
	notes TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_model_version UNIQUE (module, name, version)
);

CREATE TABLE resource_recommendations (
	id SERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	method VARCHAR(30), 
	target_type VARCHAR(20), 
	target_id INTEGER, 
	target_name VARCHAR(200), 
	rank INTEGER, 
	priority_score FLOAT, 
	allocated_units FLOAT, 
	reason TEXT, 
	details JSON, 
	is_simulated_input BOOLEAN, 
	disclaimer VARCHAR(200), 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	hashed_password VARCHAR(255) NOT NULL, 
	full_name VARCHAR(120), 
	role VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE wards (
	id SERIAL NOT NULL, 
	city_id INTEGER NOT NULL, 
	ward_no VARCHAR(20) NOT NULL, 
	name VARCHAR(160), 
	centroid_lat FLOAT, 
	centroid_lon FLOAT, 
	population INTEGER, 
	area_sqkm FLOAT, 
	geometry_geojson TEXT, 
	data_origin VARCHAR(12), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ward_city_no UNIQUE (city_id, ward_no), 
	FOREIGN KEY(city_id) REFERENCES cities (id)
);

CREATE INDEX ix_wards_city_id ON wards (city_id);

CREATE TABLE weather_observations (
	id SERIAL NOT NULL, 
	city_id INTEGER NOT NULL, 
	valid_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE, 
	is_forecast BOOLEAN NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	temperature_c FLOAT, 
	humidity_pct FLOAT, 
	rainfall_mm FLOAT, 
	wind_speed_kmh FLOAT, 
	wind_direction_deg FLOAT, 
	cloud_cover_pct FLOAT, 
	weather_code INTEGER, 
	source VARCHAR(40), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_weather UNIQUE (city_id, valid_at, is_forecast, source), 
	FOREIGN KEY(city_id) REFERENCES cities (id)
);

CREATE INDEX ix_weather_city_time ON weather_observations (city_id, valid_at);

CREATE TABLE hotspot_clusters (
	id SERIAL NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	run_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	method VARCHAR(30), 
	cluster_label INTEGER, 
	centroid_lat FLOAT, 
	centroid_lon FLOAT, 
	radius_m FLOAT, 
	n_points INTEGER, 
	severity FLOAT, 
	ward_id INTEGER, 
	params JSON, 
	members JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE INDEX ix_hotspot_kind_run ON hotspot_clusters (kind, run_at);

CREATE TABLE locations (
	id SERIAL NOT NULL, 
	city_id INTEGER NOT NULL, 
	ward_id INTEGER, 
	kind VARCHAR(30) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	source VARCHAR(40), 
	external_id VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_location_source_ext UNIQUE (source, external_id), 
	FOREIGN KEY(city_id) REFERENCES cities (id), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE INDEX ix_locations_city_id ON locations (city_id);

CREATE TABLE road_segments (
	id SERIAL NOT NULL, 
	city_id INTEGER NOT NULL, 
	ward_id INTEGER, 
	name VARCHAR(200) NOT NULL, 
	road_type VARCHAR(40), 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	geometry_geojson TEXT, 
	osm_way_id VARCHAR(30), 
	is_active BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(city_id) REFERENCES cities (id), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE INDEX ix_road_segments_city_id ON road_segments (city_id);

CREATE TABLE waste_predictions (
	id SERIAL NOT NULL, 
	ward_id INTEGER NOT NULL, 
	made_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	target_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	predicted_kg FLOAT, 
	capacity_gap_kg FLOAT, 
	priority VARCHAR(12), 
	model_version VARCHAR(60), 
	trained_on VARCHAR(12), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_waste_pred UNIQUE (ward_id, made_at, target_date), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE TABLE waste_records (
	id SERIAL NOT NULL, 
	ward_id INTEGER NOT NULL, 
	record_date TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	population INTEGER, 
	waste_kg FLOAT NOT NULL, 
	category VARCHAR(40), 
	collection_capacity_kg FLOAT, 
	collection_frequency_per_day FLOAT, 
	is_holiday BOOLEAN, 
	weather_condition VARCHAR(40), 
	data_origin VARCHAR(12) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_waste_rec UNIQUE (ward_id, record_date, category, data_origin), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE INDEX ix_waste_ward_date ON waste_records (ward_id, record_date);

CREATE TABLE alerts (
	id SERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	severity VARCHAR(12) NOT NULL, 
	message TEXT NOT NULL, 
	location_id INTEGER, 
	segment_id INTEGER, 
	ward_id INTEGER, 
	is_active BOOLEAN, 
	data_origin VARCHAR(12), 
	PRIMARY KEY (id), 
	FOREIGN KEY(location_id) REFERENCES locations (id), 
	FOREIGN KEY(segment_id) REFERENCES road_segments (id), 
	FOREIGN KEY(ward_id) REFERENCES wards (id)
);

CREATE TABLE pollution_observations (
	id SERIAL NOT NULL, 
	location_id INTEGER NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE, 
	parameter VARCHAR(20) NOT NULL, 
	value FLOAT NOT NULL, 
	unit VARCHAR(20), 
	source VARCHAR(40) NOT NULL, 
	license VARCHAR(120), 
	data_origin VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_pollution_obs UNIQUE (location_id, observed_at, parameter, source), 
	FOREIGN KEY(location_id) REFERENCES locations (id)
);

CREATE INDEX ix_poll_loc_param_time ON pollution_observations (location_id, parameter, observed_at);

CREATE TABLE pollution_predictions (
	id SERIAL NOT NULL, 
	location_id INTEGER NOT NULL, 
	made_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	target_time TIMESTAMP WITH TIME ZONE NOT NULL, 
	horizon_h INTEGER NOT NULL, 
	parameter VARCHAR(20) NOT NULL, 
	predicted_value FLOAT, 
	lower FLOAT, 
	upper FLOAT, 
	trend VARCHAR(12), 
	index_category VARCHAR(30), 
	model_version VARCHAR(60), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_pollution_pred UNIQUE (location_id, made_at, horizon_h, parameter), 
	FOREIGN KEY(location_id) REFERENCES locations (id)
);

CREATE TABLE traffic_observations (
	id SERIAL NOT NULL, 
	segment_id INTEGER NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	fetched_at TIMESTAMP WITH TIME ZONE, 
	current_speed_kmh FLOAT, 
	free_flow_speed_kmh FLOAT, 
	congestion_ratio FLOAT, 
	current_travel_time_s FLOAT, 
	confidence FLOAT, 
	road_closure BOOLEAN, 
	source VARCHAR(40) NOT NULL, 
	data_origin VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_traffic_obs UNIQUE (segment_id, observed_at, source), 
	FOREIGN KEY(segment_id) REFERENCES road_segments (id)
);

CREATE INDEX ix_traffic_seg_time ON traffic_observations (segment_id, observed_at);

CREATE TABLE traffic_predictions (
	id SERIAL NOT NULL, 
	segment_id INTEGER NOT NULL, 
	made_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	target_time TIMESTAMP WITH TIME ZONE NOT NULL, 
	horizon_min INTEGER NOT NULL, 
	predicted_ratio FLOAT, 
	predicted_speed_kmh FLOAT, 
	congestion_level VARCHAR(20), 
	lower FLOAT, 
	upper FLOAT, 
	model_version VARCHAR(60), 
	calibration_status VARCHAR(30), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_traffic_pred UNIQUE (segment_id, made_at, horizon_min), 
	FOREIGN KEY(segment_id) REFERENCES road_segments (id)
);

CREATE INDEX ix_traffic_pred_seg_target ON traffic_predictions (segment_id, target_time);
