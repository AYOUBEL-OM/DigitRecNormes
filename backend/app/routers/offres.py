import logging
import uuid
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Request, Depends, status, HTTPException, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import get_entreprise_from_token
from app.database import get_db
from app.models.offre import Offre
from app.schemas.offre import (
    OffreCreate,
    OffreEntrepriseResponse,
    OffreResponse,
    OffreResponseAvecLien,
    OffreUpdate,
)
from app.services.offre_public_access import (
    affichage_statut_offre,
    offre_accessible_publiquement,
    offre_est_expiree,
    offre_statut_manuellement_actif,
)
from app.constants.subscription_plans import get_plan
from app.services.subscription_access import (
    enforce_offer_limits,
    require_active_subscription,
)

router = APIRouter(prefix="/offres", tags=["Offres"])
logger = logging.getLogger(__name__)


def _public_apply_url(token: Optional[str]) -> str:
    """URL page publique de candidature : `/apply/{token_liens}` (alignée sur FRONTEND_PUBLIC_URL)."""
    if not token or not str(token).strip():
        return ""
    base = (get_settings().FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
    return f"{base}/apply/{token.strip()}"


def _to_entreprise_response(offre: Offre) -> OffreEntrepriseResponse:
    # Debug : vérifier la valeur ORM après chargement (niveau log DEBUG).
    logger.debug(
        "Offre ORM competences id=%s value=%r len=%s",
        getattr(offre, "id", None),
        offre.competences,
        len(offre.competences) if offre.competences else 0,
    )
    base = OffreResponse.model_validate(offre)
    dumped = base.model_dump()
    # Fallback explicite : garantit la clé JSON `competences` depuis l’ORM (Pydantic / ORM).
    dumped["competences"] = offre.competences
    return OffreEntrepriseResponse(
        **dumped,
        created_at=offre.created_at,
        lien_candidature=_public_apply_url(offre.token_liens),
        lien_public_actif=offre_accessible_publiquement(offre),
        affichage_statut=affichage_statut_offre(offre),
    )


def _get_offre_owned(
    db: Session, offre_id: UUID, entreprise_id: UUID
) -> Optional[Offre]:
    return (
        db.query(Offre)
        .filter(Offre.id == offre_id, Offre.entreprise_id == entreprise_id)
        .first()
    )


@router.post("", response_model=OffreResponseAvecLien, status_code=status.HTTP_201_CREATED)
def create_offre(
    data: OffreCreate,
    request: Request,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    sub = require_active_subscription(db, entreprise)
    plan = get_plan(sub.plan_code)
    enforce_offer_limits(db, entreprise, plan, for_new_offer=True)

    token = str(uuid.uuid4())

    offre = Offre(
        entreprise_id=entreprise.id,
        title=data.title,
        profile=data.profile,
        localisation=data.localisation,
        type_contrat=data.type_contrat,
        level=data.level,
        nombre_candidats_recherche=data.nombre_candidats_recherche,
        nombre_experience_minimun=data.nombre_experience_minimun,
        niveau_etude=data.niveau_etude,
        competences=data.competences,
        type_examens_ecrit=data.type_examens_ecrit,
        nombre_questions_orale=data.nombre_questions_orale,
        date_fin_offres=data.date_fin_offres,
        description_postes=data.description_postes,
        token_liens=token,
        status="active",
    )

    db.add(offre)
    db.commit()
    db.refresh(offre)

    return OffreResponseAvecLien(
        id=offre.id,
        title=offre.title,
        profile=offre.profile,
        localisation=offre.localisation,
        type_contrat=offre.type_contrat,
        level=offre.level,
        nombre_candidats_recherche=offre.nombre_candidats_recherche,
        nombre_experience_minimun=offre.nombre_experience_minimun,
        niveau_etude=offre.niveau_etude,
        competences=offre.competences,
        type_examens_ecrit=offre.type_examens_ecrit,
        nombre_questions_orale=offre.nombre_questions_orale,
        date_fin_offres=offre.date_fin_offres,
        description_postes=offre.description_postes,
        status=offre.status,
        token_liens=offre.token_liens,
        lien_candidature=_public_apply_url(offre.token_liens),
    )


@router.get("", response_model=List[OffreEntrepriseResponse])
def get_offres(
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Offre)
        .filter(Offre.entreprise_id == entreprise.id)
        .order_by(Offre.created_at.desc())
        .all()
    )
    return [_to_entreprise_response(o) for o in rows]


@router.get("/public/{token}")
def get_public_offre(token: str, db: Session = Depends(get_db)):
    offre = db.query(Offre).filter(Offre.token_liens == token).first()

    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien non disponible ou offre introuvable.",
        )

    if not offre_statut_manuellement_actif(offre):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette offre a été désactivée. Le lien de candidature n’est plus actif.",
        )

    if offre_est_expiree(offre):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La période de candidature pour cette offre est terminée.",
        )

    return {
        "id": str(offre.id),
        "title": offre.title,
        "profile": offre.profile,
        "localisation": offre.localisation,
        "type_contrat": offre.type_contrat,
        "level": offre.level,
        "nombre_candidats_recherche": offre.nombre_candidats_recherche,
        "nombre_experience_minimun": offre.nombre_experience_minimun,
        "niveau_etude": offre.niveau_etude,
        "competences": offre.competences,
        "type_examens_ecrit": offre.type_examens_ecrit,
        "nombre_questions_orale": offre.nombre_questions_orale,
        "date_fin_offres": offre.date_fin_offres.isoformat() if offre.date_fin_offres else None,
        "description_postes": offre.description_postes,
        "status": offre.status,
        "token_liens": offre.token_liens,
    }


@router.get("/{offre_id}", response_model=OffreEntrepriseResponse)
def get_offre_detail(
    offre_id: UUID,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    offre = _get_offre_owned(db, offre_id, entreprise.id)
    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable.",
        )
    return _to_entreprise_response(offre)


@router.patch("/{offre_id}", response_model=OffreEntrepriseResponse)
def update_offre(
    offre_id: UUID,
    data: OffreUpdate,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """
    Mise à jour d’une offre. Le champ ``token_liens`` n’est jamais modifié via cette route
    (lien de candidature stable).
    """
    offre = _get_offre_owned(db, offre_id, entreprise.id)
    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable.",
        )
    prev_status = offre.status
    payload = data.model_dump(exclude_unset=True)
    # Sécurité : jamais de réassignation du token public depuis le client
    payload.pop("token_liens", None)
    for key, value in payload.items():
        setattr(offre, key, value)

    sub = require_active_subscription(db, entreprise)
    plan = get_plan(sub.plan_code)
    if offre.status == "active" and prev_status != "active":
        enforce_offer_limits(db, entreprise, plan)

    db.add(offre)
    db.commit()
    db.refresh(offre)
    return _to_entreprise_response(offre)


@router.delete("/{offre_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_offre(
    offre_id: UUID,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """
    Désactivation manuelle (bouton « Désactiver ») : ``status`` → ``inactive``.
    Aucune suppression physique ; ``token_liens`` inchangé ; candidatures conservées.
    """
    offre = _get_offre_owned(db, offre_id, entreprise.id)
    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable.",
        )
    offre.status = "inactive"
    db.add(offre)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)