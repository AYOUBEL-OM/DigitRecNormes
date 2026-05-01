"""
Configuration de l'application via variables d'environnement.
"""
import re
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Répertoire backend/ (pour .env même si uvicorn est lancé depuis un autre cwd)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def resolve_upload_dir(setting_value: str) -> Path:
    """
    Chemin absolu des dossiers d'upload (cv, oral_answers, …), stable quel que soit le cwd.
    Les valeurs relatives sont résolues depuis ``backend/``, pas depuis le répertoire courant du processus.
    """
    p = Path((setting_value or "").strip())
    if p.is_absolute():
        return p.resolve()
    return (_BACKEND_ROOT / p).resolve()


class Settings(BaseSettings):
    """Paramètres de l'application ATS."""

    # === PostgreSQL / Supabase ===
    DATABASE_URL: str = ""  # Format: postgresql://user:pass@host:5432/db?sslmode=require

    # Variables PostgreSQL (utilisées si DATABASE_URL est vide)
    POSTGRES_HOST: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DATABASE: str = "postgres"
    POSTGRES_SSL_MODE: str = "require"  # Obligatoire pour Supabase

    # Application
    APP_NAME: str = "DigitRec"
    DEBUG: bool = False

    # JWT — durée de session « navigateur » jusqu’à déconnexion explicite (logout).
    # Surchargeable via .env (ex. 10080 = 7 jours, 525600 ≈ 1 an).
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 jours

    # Upload CV
    UPLOAD_DIR: str = "uploads/cv"
    ORAL_RECORDINGS_DIR: str = "uploads/oral_recordings"
    ORAL_ANSWERS_DIR: str = "uploads/oral_answers"
    ORAL_SNAPSHOTS_DIR: str = "uploads/oral_snapshots"
    ORAL_PHOTOS_DIR: str = "uploads/oral_photos"
    MAX_CV_SIZE_MB: int = 5
    ALLOWED_CV_EXTENSIONS: str = "pdf,doc,docx"

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_KEY: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-70b-versatile"
    # Transcription audio entretien oral : Groq Whisper uniquement (`oral_answer_analysis.transcribe_audio`).
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""

    FRONTEND_PUBLIC_URL: str = "http://localhost:8080"

    # Stripe : secrets et price IDs via `.env` (mode test : clés sk_test_ / price_ du Dashboard test).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Price IDs Dashboard → Produits → Prix récurrents (même compte / mode que STRIPE_SECRET_KEY).
    STRIPE_PRICE_ID_LIMITED: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STRIPE_PRICE_ID_LIMITED",
            "STRIPE_PRICE_ID_PACK_LIMITE",
        ),
    )
    STRIPE_PRICE_ID_UNLIMITED: str = Field(
        default="",
        validation_alias=AliasChoices(
            "STRIPE_PRICE_ID_UNLIMITED",
            "STRIPE_PRICE_ID_PACK_ILLIMITE",
        ),
    )

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def supabase_key_resolved(self) -> str:
        """Clé API Supabase (service role ou clé alternative depuis .env)."""
        return (self.SUPABASE_SERVICE_KEY or self.SUPABASE_KEY or "").strip()

    @property
    def database_url(self) -> str:
        """URL de connexion PostgreSQL pour SQLAlchemy."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL.strip()
            # Corriger l’hôte pooler Supabase (db.<ref>.supabase.co → <ref>.supabase.co) si besoin
            url = re.sub(
                r"db\.([a-z0-9]+)\.supabase\.co",
                r"\1.supabase.co",
                url,
                flags=re.IGNORECASE,
            )
            if "supabase.co" in url and "sslmode" not in url:
                separator = "&" if "?" in url else "?"
                return f"{url}{separator}sslmode=require"
            return url

        base_url = (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"
        )
        return f"{base_url}?sslmode={self.POSTGRES_SSL_MODE}"


@lru_cache
def get_settings() -> Settings:
    """Retourne les paramètres (mis en cache)."""
    return Settings()
