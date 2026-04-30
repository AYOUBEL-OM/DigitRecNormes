"""
Accès aux abonnements : lecture en base (source de vérité) et quotas d’offres.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.constants.subscription_plans import SaaSPlan, canonical_plan_code, get_plan, plan_rank

# Message unique demandé (403 création d’offre + API /me)
FREE_TRIAL_OFFERS_EXHAUSTED_MESSAGE = (
    "Vous avez utilisé votre offre gratuite. Veuillez choisir un pack pour créer de nouvelles offres."
)
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.subscription import Subscription

if TYPE_CHECKING:
    from app.models.entreprise import Entreprise


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_active_subscription_for_entreprise(
    db: Session,
    entreprise_id,
) -> Optional[Subscription]:
    """
    Abonnement « actif » non expiré. Si plusieurs lignes actives (ex. essai + pack payé mal fusionné),
    on choisit le plan le plus élevé (UNLIMITED > LIMITED > TRIAL) puis le plus récent.
    """
    rows = (
        db.query(Subscription)
        .filter(
            Subscription.entreprise_id == entreprise_id,
            Subscription.status == "active",
        )
        .all()
    )
    if not rows:
        return None
    now = _now_utc()
    candidates: list[Subscription] = []
    for sub in rows:
        if sub.end_date is not None and sub.end_date < now:
            continue
        candidates.append(sub)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _ts(s: Subscription) -> float:
        u = s.updated_at
        if u is None:
            return 0.0
        return u.timestamp()

    return max(
        candidates,
        key=lambda s: (plan_rank(s.plan_code), _ts(s)),
    )


def get_active_plan_for_entreprise(db: Session, entreprise_id) -> Optional[SaaSPlan]:
    sub = get_active_subscription_for_entreprise(db, entreprise_id)
    if not sub:
        return None
    try:
        return get_plan(sub.plan_code)
    except KeyError:
        return None


def ensure_default_trial_subscription(db: Session, entreprise_id) -> None:
    """Crée un abonnement d’essai actif si l’entreprise n’en a aucun (comptes existants)."""
    if get_active_subscription_for_entreprise(db, entreprise_id):
        return
    row = Subscription(
        entreprise_id=entreprise_id,
        plan_code="TRIAL",
        billing_cycle="free",
        status="active",
        currency="mad",
    )
    db.add(row)
    db.commit()


def require_active_subscription(db: Session, entreprise: "Entreprise") -> Subscription:
    ensure_default_trial_subscription(db, entreprise.id)
    sub = get_active_subscription_for_entreprise(db, entreprise.id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUBSCRIPTION_REQUIRED",
                "message": "Un abonnement actif est requis pour cette action.",
            },
        )
    return sub


def require_plan(db: Session, entreprise: "Entreprise", minimum_plan_code: str) -> Tuple[Subscription, SaaSPlan]:
    """Garde-fou par « rang » de plan (TRIAL < LIMITED < UNLIMITED)."""
    sub = require_active_subscription(db, entreprise)
    try:
        plan_def = get_plan(sub.plan_code)
        min_code = canonical_plan_code(minimum_plan_code)
        if plan_rank(plan_def.code) < plan_rank(min_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLAN_INSUFFICIENT",
                    "message": f"La formule {min_code} ou supérieure est requise.",
                    "current_plan": plan_def.code,
                    "required_plan": min_code,
                },
            )
        return sub, plan_def
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SUBSCRIPTION_INVALID", "message": "Plan d’abonnement inconnu ou invalide."},
        ) from None


def require_plan_for_entreprise_id(db: Session, entreprise_id, minimum_plan_code: str) -> Tuple[Subscription, SaaSPlan]:
    ensure_default_trial_subscription(db, entreprise_id)
    sub = get_active_subscription_for_entreprise(db, entreprise_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUBSCRIPTION_REQUIRED",
                "message": "L’entreprise associée n’a pas d’abonnement actif.",
            },
        )
    try:
        plan_def = get_plan(sub.plan_code)
        min_code = canonical_plan_code(minimum_plan_code)
        if plan_rank(plan_def.code) < plan_rank(min_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PLAN_INSUFFICIENT",
                    "message": f"La formule {min_code} ou supérieure est requise pour cette fonctionnalité.",
                    "current_plan": plan_def.code,
                    "required_plan": min_code,
                },
            )
        return sub, plan_def
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SUBSCRIPTION_INVALID", "message": "Plan d’abonnement invalide."},
        ) from None


def count_active_offers(db: Session, entreprise_id) -> int:
    return (
        db.query(Offre)
        .filter(Offre.entreprise_id == entreprise_id, Offre.status == "active")
        .count()
    )


def count_all_offers(db: Session, entreprise_id) -> int:
    """Toutes les offres créées (pas de suppression physique dans le modèle actuel)."""
    return db.query(Offre).filter(Offre.entreprise_id == entreprise_id).count()


def enforce_offer_limits(
    db: Session,
    entreprise: "Entreprise",
    plan: SaaSPlan,
    *,
    for_new_offer: bool = False,
) -> None:
    if plan.max_active_offers is None:
        return
    if plan.is_trial:
        # Essai : quota sur le nombre total d’offres créées (une seule gratuite).
        # Ne pas bloquer la réactivation d’une offre déjà existante (PATCH status → active).
        if not for_new_offer:
            return
        n = count_all_offers(db, entreprise.id)
        cap = plan.max_active_offers
        if n >= cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=FREE_TRIAL_OFFERS_EXHAUSTED_MESSAGE,
            )
        return
    n = count_active_offers(db, entreprise.id)
    if n >= plan.max_active_offers:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OFFER_LIMIT_REACHED",
                "message": (
                    f"Nombre maximal d’offres actives atteint pour votre formule ({plan.max_active_offers}). "
                    "Passez au pack illimité ou désactivez une offre existante."
                ),
                "max_active_offers": plan.max_active_offers,
            },
        )


def entreprise_allows_ai(db: Session, entreprise_id) -> bool:
    return get_active_subscription_for_entreprise(db, entreprise_id) is not None


def entreprise_allows_proctoring(db: Session, entreprise_id) -> bool:
    return get_active_subscription_for_entreprise(db, entreprise_id) is not None


def get_entreprise_id_for_oral_session(db: Session, oral) -> UUID:
    cand = db.query(Candidature).filter(Candidature.id == oral.id_candidature).first()
    if not cand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidature introuvable.",
        )
    offre = db.query(Offre).filter(Offre.id == cand.offre_id).first()
    if not offre or not offre.entreprise_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable.",
        )
    return offre.entreprise_id
