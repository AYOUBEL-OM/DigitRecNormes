"""
Affiche les UUID des offres dont le titre correspond au motif (ILIKE).

Usage (depuis le dossier backend, avec .env ou DATABASE_URL chargé) :
  python scripts/find_offre_by_title.py "Developpeur"
  python scripts/find_offre_by_title.py "%web mobile%"

Ensuite ouvrez dans le navigateur (connecté) :
  http://localhost:8080/quiz/<UUID>
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permet ``import app`` depuis backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python scripts/find_offre_by_title.py "motif titre"')
        sys.exit(1)
    pattern = sys.argv[1].strip()
    if not pattern:
        print("Motif vide.")
        sys.exit(1)
    if "%" not in pattern:
        pattern = f"%{pattern}%"

    settings = get_settings()
    url = settings.database_url
    if not url:
        print("DATABASE_URL / configuration PostgreSQL manquante.")
        sys.exit(1)

    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id::text, title, type_examens_ecrit "
                "FROM offres WHERE title ILIKE :pat ORDER BY created_at DESC NULLS LAST LIMIT 20"
            ),
            {"pat": pattern},
        ).fetchall()

    if not rows:
        print(f"Aucune offre pour le motif ILIKE {pattern!r}")
        sys.exit(0)

    print(f"{'id':<40}  {'type_examens_ecrit':<12}  title")
    print("-" * 100)
    for rid, title, tex in rows:
        t = (title or "")[:60]
        te = tex or ""
        print(f"{rid}  {te:<12}  {t}")
    print()
    first = rows[0][0]
    print(f"Exemple URL test : http://localhost:8080/quiz/{first}")


if __name__ == "__main__":
    main()
