from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_candidat_from_token
from app.core.security import creer_access_token, verifier_mot_de_passe
from app.database import get_db
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.test_ecrit import TestEcrit
from app.services import quiz_service

router = APIRouter(tags=["quiz"])


class EvaluateBody(BaseModel):
    code: str = Field(..., description="Réponse du candidat (code ou texte)")
    consigne: str = Field(..., description="Consigne / description de l'exercice")


class QuizVerifyForTestBody(BaseModel):
    email: str = Field(..., description="Email du compte candidat")
    mot_de_passe: str = Field(..., description="Mot de passe")
    offre_id: UUID = Field(..., description="Identifiant de l’offre (test)")


class TestsEcritCreateBody(BaseModel):
    id_candidature: UUID
    score_ecrit: float = Field(..., ge=0, le=100)
    status_reussite: bool

@router.get("/quiz/config/{identifier}")
async def quiz_config(identifier: UUID, db: Session = Depends(get_db)):
    """
    Vérifie l'ID de l'offre et renvoie la config.
    """
    offre = db.query(Offre).filter(Offre.id == identifier).first()
    if not offre:
        raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

    try:
        # هنا كنصيفطو الـ Offre Object كامل باش الـ service يخدم مرتاح
        return quiz_service.get_quiz_config(db, offre)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/generate/{identifier}")
async def generate_quiz(identifier: UUID, db: Session = Depends(get_db)):
    """
    Génère le quiz en utilisant l'ID de l'offre.
    """
    offre = db.query(Offre).filter(Offre.id == identifier).first()
    if not offre:
        raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

    try:
        return quiz_service.generate_quiz_content(db, offre)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluate")
async def evaluate(body: EvaluateBody):
    try:
        return quiz_service.evaluate_submission(body.code, body.consigne)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Evaluation failed")


@router.post("/quiz/verify-for-test")
def quiz_verify_for_test(body: QuizVerifyForTestBody, db: Session = Depends(get_db)):
    """
    Authentifie le candidat et vérifie qu’une candidature existe pour l’offre du test.
    Renvoie l’id de candidature et un JWT candidat pour les appels protégés (enregistrement du résultat).
    """
    offre = db.query(Offre).filter(Offre.id == body.offre_id).first()
    if not offre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offre introuvable.")

    candidat = db.query(Candidat).filter(Candidat.email == body.email.strip()).first()
    if not candidat or not verifier_mot_de_passe(body.mot_de_passe, candidat.mot_de_passe_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect.",
        )

    candidature = (
        db.query(Candidature)
        .filter(
            Candidature.candidat_id == candidat.id,
            Candidature.offre_id == body.offre_id,
        )
        .first()
    )
    if not candidature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aucune candidature enregistrée pour cette offre. Vous devez d’abord postuler.",
        )

    token = creer_access_token(
        data={"sub": str(candidat.id), "email": candidat.email, "type": "candidat"}
    )

    return {
        "id_candidature": str(candidature.id),
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(candidat.id),
            "email": candidat.email,
            "type": "candidat",
        },
    }


@router.post("/quiz/tests-ecrits", status_code=status.HTTP_201_CREATED)
def create_tests_ecrit(
    body: TestsEcritCreateBody,
    db: Session = Depends(get_db),
    candidat: Candidat = Depends(get_candidat_from_token),
):
    """Enregistre un résultat de test écrit pour la candidature du candidat authentifié."""
    candidature = db.query(Candidature).filter(Candidature.id == body.id_candidature).first()
    if not candidature:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidature introuvable.")
    if str(candidature.candidat_id) != str(candidat.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette candidature ne correspond pas à votre compte.",
        )

    row = TestEcrit(
        id_candidature=body.id_candidature,
        score_ecrit=body.score_ecrit,
        status_reussite=body.status_reussite,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "id_candidature": str(row.id_candidature),
        "score_ecrit": row.score_ecrit,
        "status_reussite": row.status_reussite,
    }