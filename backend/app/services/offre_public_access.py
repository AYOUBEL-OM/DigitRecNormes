"""
Règles d’accès public aux offres (candidature / lien token) — sans modifier le schéma DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.offre import Offre


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def offre_est_expiree(offre: Offre) -> bool:
    """True si ``date_fin_offres`` est strictement dans le passé."""
    if offre.date_fin_offres is None:
        return False
    end = offre.date_fin_offres
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return now_utc() > end


def offre_statut_manuellement_actif(offre: Offre) -> bool:
    """False uniquement si désactivée manuellement (``status == 'inactive'``)."""
    s = (offre.status or "").strip().lower()
    return s != "inactive"


def offre_accessible_publiquement(offre: Offre) -> bool:
    """Lien /apply/{token} utilisable : actif ET non expiré."""
    if not offre_statut_manuellement_actif(offre):
        return False
    if offre_est_expiree(offre):
        return False
    return True


def affichage_statut_offre(offre: Offre) -> str:
    """
    Libellé métier pour l’UI entreprise : ``expirée`` | ``inactive`` | ``active``.
    L’expiration prime sur le statut manuel pour l’affichage.
    """
    if offre_est_expiree(offre):
        return "expirée"
    if not offre_statut_manuellement_actif(offre):
        return "inactive"
    return "active"
