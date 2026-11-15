from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401 - ثبت مدل‌ها در metadata
from app.routes import auth, ads, admin, integrations, jibit

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Lightweight SQLite-compatible additive migration for existing installations.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "ad_campaigns" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("ad_campaigns")}
        with engine.begin() as conn:
            if "video_url" not in cols: conn.execute(text("ALTER TABLE ad_campaigns ADD COLUMN video_url TEXT NOT NULL DEFAULT ''"))
            if "media_type" not in cols: conn.execute(text("ALTER TABLE ad_campaigns ADD COLUMN media_type VARCHAR(20) NOT NULL DEFAULT 'image'"))
    yield

app = FastAPI(title=settings.app_name, version="0.1.0", description="API آزمایشی اپلیکیشن نیازتو", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list or ["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(ads.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router)
app.include_router(integrations.router, prefix=settings.api_v1_prefix)
app.include_router(jibit.router, prefix=settings.api_v1_prefix)
_upload_dir = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parent / "uploads")))
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")

@app.get("/", tags=["وضعیت"])
def root():
    return {"message": "Niyazeto API is running", "docs": "/docs"}

@app.get("/health", tags=["وضعیت"])
def health():
    return {"status": "ok", "service": "niyazeto-backend"}
