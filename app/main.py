from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import create_database
from app.keitaro import DemoClient, KeitaroClient, TrackerError
from app.schemas import CreateCampaign, OfferAction
from app.service import CampaignService

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, tracker=None):
    settings = settings or Settings.from_env()
    engine, sessions = create_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        client = tracker or (DemoClient(sessions) if settings.demo_mode else KeitaroClient(settings))
        app.state.service = CampaignService(settings, client, sessions)
        try:
            yield
        finally:
            client.close()
            engine.dispose()

    app = FastAPI(title="Adrobot · Keitaro wrapper", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Запрос с другого сайта запрещён."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(TrackerError)
    async def tracker_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/api/config")
    def config():
        return {"demo_mode": settings.demo_mode, "prefix": settings.prefix, "tracker_url": settings.keitaro_url if not settings.demo_mode else None}

    @app.get("/api/references")
    def references(request: Request):
        return request.app.state.service.references()

    @app.get("/api/campaigns")
    def campaigns(request: Request):
        with request.app.state.service.lock:
            return request.app.state.service.list_campaigns()

    @app.post("/api/campaigns", status_code=201)
    def create(data: CreateCampaign, request: Request):
        return request.app.state.service.create(data)

    @app.post("/api/campaigns/{campaign_id}/refresh")
    def refresh(campaign_id: int, request: Request):
        if campaign_id <= 0:
            raise HTTPException(422, "ID должен быть положительным.")
        return request.app.state.service.refresh(campaign_id)

    @app.post("/api/campaigns/{campaign_id}/streams/{stream_id}/offers")
    def change(campaign_id: int, stream_id: int, data: OfferAction, request: Request):
        return request.app.state.service.change_offer(campaign_id, stream_id, data)

    @app.get("/api/campaigns/{campaign_id}/stats")
    def stats(campaign_id: int, request: Request):
        return request.app.state.service.stats(campaign_id)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
