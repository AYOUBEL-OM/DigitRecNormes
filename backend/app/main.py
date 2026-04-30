"""
ATS Recrutement - Point d'entrée FastAPI.
"""
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings, resolve_upload_dir
from app.routers import auth_entreprise, auth_candidat, offres, candidatures, entreprises
from app.routers.dashboard import router as dashboard_router
from app.routers import oral_interview
from app.routers import subscriptions as subscriptions_router
from app.api.endpoints import quiz as quiz_endpoints

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="Plateforme de recrutement SaaS - Gestion des offres et candidatures",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    # Autorise explicitement les scénarios avec credentials (même si on utilise surtout Authorization: Bearer).
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Routes
app.include_router(auth_entreprise.router, prefix="/api")
app.include_router(auth_candidat.router, prefix="/api")
app.include_router(offres.router, prefix="/api")
app.include_router(candidatures.router, prefix="/api")
app.include_router(entreprises.router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(quiz_endpoints.router, prefix="/api")
app.include_router(oral_interview.router, prefix="/api")
app.include_router(subscriptions_router.router, prefix="/api")

# Static files (chemins alignés sur resolve_upload_dir : même racine que save-answer / finalize)
_upload_cv_dir = resolve_upload_dir(settings.UPLOAD_DIR)
_upload_cv_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/cv",
    StaticFiles(directory=str(_upload_cv_dir)),
    name="cv_uploads",
)

_oral_dir = resolve_upload_dir(settings.ORAL_RECORDINGS_DIR)
_oral_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/oral_recordings",
    StaticFiles(directory=str(_oral_dir)),
    name="oral_recordings",
)

_oral_answers_dir = resolve_upload_dir(settings.ORAL_ANSWERS_DIR)
_oral_answers_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/oral_answers",
    StaticFiles(directory=str(_oral_answers_dir)),
    name="oral_answers",
)

_oral_snapshots_dir = resolve_upload_dir(settings.ORAL_SNAPSHOTS_DIR)
_oral_snapshots_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/oral_snapshots",
    StaticFiles(directory=str(_oral_snapshots_dir)),
    name="oral_snapshots",
)

_oral_photos_dir = resolve_upload_dir(settings.ORAL_PHOTOS_DIR)
_oral_photos_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/oral_photos",
    StaticFiles(directory=str(_oral_photos_dir)),
    name="oral_photos",
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/")
def root():
    return {
        "message": "Bienvenue sur l'API ATS Recrutement",
        "docs": "/docs"
    }

@app.get("/sante")
def sante():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    detail = str(exc)
    if settings.DEBUG:
        detail += "\n" + traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": detail, "type": type(exc).__name__},
    )