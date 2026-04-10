"""
Configuration de l'application via variables d'environnement.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Paramètres de l'application ATS."""

    # === PostgreSQL / Supabase ===
    DATABASE_URL: str = ""  # Format: postgresql://user:pass@host:5432/db?sslmode=require

    # Variables PostgreSQL (utilisées si DATABASE_URL est vide)
    POSTGRES_HOST: str = "rhedlvxkmbugidditvow.supabase.co"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DATABASE: str = "postgres"
    POSTGRES_SSL_MODE: str = "require"  # Obligatoire pour Supabase

    # Application
    APP_NAME: str = "DigitRec"
    DEBUG: bool = False

    # JWT
    SECRET_KEY: str = "changez-moi-en-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Upload CV
    UPLOAD_DIR: str = "uploads/cv"
    MAX_CV_SIZE_MB: int = 5
    ALLOWED_CV_EXTENSIONS: str = "pdf,doc,docx"

    SUPABASE_URL: str = "https://rhedlvxkmbugidditvow.supabase.co"
    SUPABASE_SERVICE_KEY: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-70b-versatile"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    @property
    def database_url(self) -> str:
        """URL de connexion PostgreSQL pour SQLAlchemy."""
        if self.DATABASE_URL:
            # Corriger le host si nécessaire
            url = self.DATABASE_URL.replace("db.rhedlvxkmbugidditvow.supabase.co", "rhedlvxkmbugidditvow.supabase.co")
            # S'assurer que sslmode=require pour Supabase
            if "supabase.co" in url and "sslmode" not in url:
                separator = "&" if "?" in url else "?"
                return f"{url}{separator}sslmode=require"
            return url
        
        # Construction manuelle avec support SSL
        base_url = (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"
        )
        return f"{base_url}?sslmode={self.POSTGRES_SSL_MODE}"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Retourne les paramètres (mis en cache)."""
    return Settings()