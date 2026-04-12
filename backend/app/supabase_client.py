# app/supabase_client.py
"""Client Supabase : initialisation paresseuse après lecture du .env (évite l'erreur « key is required » au chargement)."""
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    url = (settings.SUPABASE_URL or "").strip()
    key = settings.supabase_key_resolved
    if not url or not key:
        raise RuntimeError(
            "Configuration Supabase incomplète : définissez SUPABASE_URL et "
            "SUPABASE_SERVICE_KEY (ou SUPABASE_KEY) dans backend/.env"
        )
    return create_client(url, key)
