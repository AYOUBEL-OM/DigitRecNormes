"""
ATS Recrutement - Point d'entrée FastAPI.
"""
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import auth_entreprise, auth_candidat, offres, candidatures
from app.routers.dashboard import router as dashboard_router
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
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Routes
app.include_router(auth_entreprise.router, prefix="/api")
app.include_router(auth_candidat.router, prefix="/api")
app.include_router(offres.router, prefix="/api")
app.include_router(candidatures.router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(quiz_endpoints.router, prefix="/api")

# Static files
_upload_cv_dir = Path(settings.UPLOAD_DIR)
_upload_cv_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads/cv",
    StaticFiles(directory=str(_upload_cv_dir.resolve())),
    name="cv_uploads",
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