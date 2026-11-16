# UrbanSense AI: Smart City Intelligence for Bhubaneswar
Free-tier, college-level project. Status: **Phase 3 complete**: foundation, ingestion, weather, OpenAQ air quality + CPCB-style index, forecasting pipeline (train/evaluate/register/predict) and APIs, 69 tests (ML tests skip automatically where ML libraries are blocked). Phase 4A traffic (TomTom collector, segment discovery, APIs, hotspot ranking) added. Next: traffic forecasting once data has accumulated.

## Run locally (no API keys needed yet)
```bash
cp .env.example .env            # then edit: set JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.seed          # creates tables (SQLite by default), city, sources, admin
uvicorn app.main:app --reload   # open http://127.0.0.1:8000/docs
python -m pytest -q             # run tests
```
Keys and where they go: see `docs/API_KEYS_GUIDE.md`. Design changes from the original spec: `docs/DESIGN_DECISIONS.md`.
Data attribution: TomTom, OpenAQ (per-station licenses), Open-Meteo (CC BY 4.0, non-commercial), OpenStreetMap contributors.

Ingestion & scheduling: see `docs/INGESTION.md`.
Air quality: see `docs/AIR_QUALITY.md`.
ML details and commands: `docs/ML_DOCUMENTATION.md`.
Colab training path: `notebooks/train_air_quality_colab.ipynb`.
Traffic: see `docs/TRAFFIC.md`.
