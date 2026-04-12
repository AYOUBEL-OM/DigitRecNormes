import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import verifier_mot_de_passe
from app.database import get_db
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.test_ecrit import TestEcrit
from app.schemas.quiz import (
    QuizVerificationRequest,
    QuizVerificationResponse,
    TestResultCreate,
    TestResultResponse,
)
from app.services import quiz_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quiz"])


class EvaluateBody(BaseModel):
    code: str = Field(..., description="Réponse du candidat (code ou texte)")
    consigne: str = Field(..., description="Consigne / description de l'exercice")


@router.get("/quiz/config/{identifier}")
async def quiz_config(identifier: UUID, db: Session = Depends(get_db)):
    """
    Vérifie l'ID de l'offre et renvoie la config.
    """
    try:
        offre = db.query(Offre).filter(Offre.id == identifier).first()
        if not offre:
            raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

        return quiz_service.get_quiz_config(db, offre)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("quiz_config DB error")
        raise HTTPException(status_code=500, detail="Erreur base de données") from e
    except Exception as e:
        logger.exception("quiz_config error")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/generate/{identifier}")
async def generate_quiz(identifier: UUID, db: Session = Depends(get_db)):
    """
    Génère le quiz en utilisant l'ID de l'offre.
    """
    try:
        offre = db.query(Offre).filter(Offre.id == identifier).first()
        if not offre:
            raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

        return quiz_service.generate_quiz_content(db, offre)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("generate_quiz DB error")
        raise HTTPException(status_code=500, detail="Erreur base de données") from e
    except Exception as e:
        logger.exception("generate_quiz error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/evaluate")
async def evaluate(body: EvaluateBody):
    try:
        return quiz_service.evaluate_submission(body.code, body.consigne)
    except Exception as e:
        logger.exception("evaluate error")
        raise HTTPException(status_code=500, detail="Evaluation failed") from e


@router.post("/quiz/verify-for-test", response_model=QuizVerificationResponse)
async def verify_for_test(body: QuizVerificationRequest, db: Session = Depends(get_db)):
    """
    Vérifie email / mot de passe et l’existence d’une candidature pour l’offre.
    Retourne id_candidature.
    """
    email_norm = body.email.strip().lower()
    try:
        offre = db.query(Offre).filter(Offre.id == body.offre_id).first()
        if not offre:
            raise HTTPException(status_code=404, detail="Offre introuvable")

        candidat = db.query(Candidat).filter(Candidat.email == email_norm).first()
        if not candidat or not verifier_mot_de_passe(body.password, candidat.mot_de_passe_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

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
                status_code=400,
                detail="Aucune candidature pour cette offre. Postulez d’abord.",
            )

        return QuizVerificationResponse(id_candidature=candidature.id)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("verify_for_test DB error")
        raise HTTPException(status_code=500, detail="Erreur base de données") from e
    except Exception as e:
        logger.exception("verify_for_test error")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


@router.post("/quiz/submit-test-result", response_model=TestResultResponse)
async def submit_test_result(body: TestResultCreate, db: Session = Depends(get_db)):
    """
    Enregistre le résultat du test écrit. status_reussite = True si score_ecrit >= 70.
    """
    try:
        candidature = (
            db.query(Candidature).filter(Candidature.id == body.id_candidature).first()
        )
        if not candidature:
            raise HTTPException(status_code=400, detail="Candidature introuvable")

        status_ok = body.score_ecrit >= 70
        row = TestEcrit(
            id=uuid.uuid4(),
            id_candidature=body.id_candidature,
            score_ecrit=float(body.score_ecrit),
            status_reussite=status_ok,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return TestResultResponse(
            id=row.id,
            id_candidature=row.id_candidature,
            score_ecrit=row.score_ecrit,
            status_reussite=row.status_reussite,
        )
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        logger.warning("submit_test_result integrity: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Impossible d’enregistrer le résultat (données invalides ou doublon).",
        ) from e
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("submit_test_result DB error")
        raise HTTPException(status_code=500, detail="Erreur base de données") from e
    except Exception as e:
        db.rollback()
        logger.exception("submit_test_result error")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e
