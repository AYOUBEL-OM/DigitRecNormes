"""
Connexion à la base de données PostgreSQL via SQLAlchemy.
"""

from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

# Charger backend/.env même si le processus n’est pas lancé depuis ce dossier
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env")

# 📌 DATABASE URL من config
settings = get_settings()
DATABASE_URL = settings.database_url

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")

# 📌 Engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True,  # Pour debug en local
)

# 📌 Session
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# 📌 Base
Base = declarative_base()


def get_db():
    """Session dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()