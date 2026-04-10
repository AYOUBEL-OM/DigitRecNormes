"""
Connexion à la base de données PostgreSQL via SQLAlchemy.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

# Charger .env automatiquement
load_dotenv()

# 📌 DATABASE URL من config
settings = get_settings()
DATABASE_URL = settings.database_url

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables")

print(f"🔧 DATABASE_URL={DATABASE_URL}")

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