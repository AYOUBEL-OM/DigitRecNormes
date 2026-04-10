import uuid
from typing import List

from fastapi import APIRouter, Request, Depends, status, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_entreprise_from_token
from app.database import get_db
from app.models.offre import Offre
from app.schemas.offre import OffreCreate, OffreResponse, OffreResponseAvecLien

router = APIRouter(prefix="/offres", tags=["Offres"])

FRONTEND_BASE_URL = "http://localhost:8080"


def _lien(token: str) -> str:
    return f"{FRONTEND_BASE_URL}/apply/{token}"


@router.post("", response_model=OffreResponseAvecLien, status_code=status.HTTP_201_CREATED)
def create_offre(
    data: OffreCreate,
    request: Request,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
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
        lien_candidature=_lien(offre.token_liens),
    )


@router.get("", response_model=List[OffreResponse])
def get_offres(
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    return (
        db.query(Offre)
        .filter(Offre.entreprise_id == entreprise.id)
        .order_by(Offre.created_at.desc())
        .all()
    )


@router.get("/public/{token}")
def get_public_offre(token: str, db: Session = Depends(get_db)):
    offre = (
        db.query(Offre)
        .filter(Offre.token_liens == token, Offre.status == "active")
        .first()
    )

    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable ou inactive.",
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