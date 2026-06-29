"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.deps import bootstrap_owner
from .api.routes import router
from .config import get_settings
from .db import SessionLocal, init_db

# Keep request bodies / prompts out of logs by default.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_for_runtime()
    init_db()
    with SessionLocal() as session:
        bootstrap_owner(session)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="better-email", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # never "*"
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "llm_provider": settings.llm_provider, "connector": settings.connector}

    app.include_router(router)

    # Serve the built frontend (single-container deploy) when present.
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            target = dist / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
