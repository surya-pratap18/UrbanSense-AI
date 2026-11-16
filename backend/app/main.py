import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, dashboard, ingest, models, pollution, traffic, weather
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0",
              description="Smart-city intelligence for Bhubaneswar. Data states: LIVE / DELAYED / HISTORICAL / SIMULATED / UNAVAILABLE.")

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(weather.router)
app.include_router(pollution.router)
app.include_router(traffic.router)
app.include_router(models.router)
app.include_router(ingest.router)


@app.get("/api/health", tags=["Health"])
def health():
    """Cheap endpoint for uptime pings (keeps the free Render instance warm)."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}
