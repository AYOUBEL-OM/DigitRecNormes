import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import get_entreprise_from_token
from app.core.security import verifier_mot_de_passe
from app.database import get_db
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.test_ecrit import TestEcrit
from app.services.subscription_access import require_plan, require_plan_for_entreprise_id
from app.schemas.quiz import (
    QuizVerificationRequest,
    QuizVerificationResponse,
    TestResultCreate,
    TestResultResponse,
)
from app.services import quiz_service
from app.services.quiz_service import EvaluationTechnicalFailure
from app.services.email_service import ensure_oral_access_and_maybe_email
from app.services.fallback_qcm_bank import (
    build_exercice_fallback_payload,
    build_qcm_fallback_payload,
)
from app.services.morocco_text_pipeline import apply_pipeline_to_quiz_payload
from app.services.qcm_normalization import recompute_qcm_snapshot_v1
from app.services.written_quiz_report_service import build_written_quiz_report_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quiz"])


def _generate_quiz_fallback_payload(db: Session, offre: Offre) -> dict:
    """Repli IA : 35 QCM métier (comptabilité marocaine) ou exercice statique selon l’offre."""
    config = quiz_service.get_quiz_config(db, offre)
    qt = str(config.get("quiz_type") or "").lower()
    title = str(config.get("title") or "Poste")
    if "exercice" in qt:
        raw = build_exercice_fallback_payload(config["quiz_type"], title)
    else:
        raw = build_qcm_fallback_payload(config["quiz_type"], title)
    return apply_pipeline_to_quiz_payload(raw)


class EvaluateBody(BaseModel):
    code: str = Field(..., description="Réponse du candidat (code ou texte)")
    consigne: str = Field(..., description="Consigne / description de l'exercice")
    offre_id: UUID = Field(..., description="Offre associée (contrôle d’accès côté serveur)")


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
    Génère le quiz en utilisant l'ID de l'offre (flux **candidat** public).

    Pour un exercice : l’énoncé est renvoyé, pas de correction / solution (le code d’éditeur
    côté client est un stub — voir ``sanitize_exercice_payload_for_candidate``).
    """
    try:
        offre = db.query(Offre).filter(Offre.id == identifier).first()
        if not offre:
            raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

        if offre.entreprise_id:
            require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")

        try:
            return quiz_service.generate_quiz_content(db, offre)
        except EvaluationTechnicalFailure as e:
            print("AI GENERATION ERROR:", str(e))
            logger.warning("generate_quiz: AI failure — fallback questions (%s)", e)
            return JSONResponse(status_code=200, content=_generate_quiz_fallback_payload(db, offre))
        except Exception as e:
            print("AI GENERATION ERROR:", str(e))
            logger.exception("generate_quiz: AI failure — fallback questions")
            return JSONResponse(status_code=200, content=_generate_quiz_fallback_payload(db, offre))
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("generate_quiz DB error")
        raise HTTPException(status_code=500, detail="Erreur base de données") from e
    except Exception as e:
        logger.exception("generate_quiz error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/evaluate")
async def evaluate(body: EvaluateBody, db: Session = Depends(get_db)):
    try:
        offre = db.query(Offre).filter(Offre.id == body.offre_id).first()
        if not offre:
            raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")
        if offre.entreprise_id:
            require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")

        return quiz_service.evaluate_submission(body.code, body.consigne)
    except EvaluationTechnicalFailure as e:
        logger.warning("evaluate: échec technique — %s", e)
        if str(e) == "RATE_LIMIT":
            detail = (
                "Le service d'évaluation est momentanément saturé. "
                "Réessayez dans quelques instants."
            )
        else:
            detail = "Évaluation technique temporairement indisponible. Réessayez dans quelques instants."
        raise HTTPException(status_code=503, detail=detail) from e
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

        if offre.entreprise_id:
            require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")

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
    Enregistre le résultat du test écrit.

    La colonne ``status_reussite`` est la source de vérité métier pour la réussite au test écrit.
    Aujourd'hui elle est dérivée du score (>= 70) uniquement au moment de l'insertion ; le flux
    oral (token + email) ne s'appuie que sur ``row.status_reussite`` après commit.
    """
    try:
        candidature = (
            db.query(Candidature).filter(Candidature.id == body.id_candidature).first()
        )
        if not candidature:
            raise HTTPException(status_code=400, detail="Candidature introuvable")

        offre = db.query(Offre).filter(Offre.id == candidature.offre_id).first()
        if offre and offre.entreprise_id:
            require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")

        detail_snap = body.detail_snapshot
        score_final = float(body.score_ecrit)
        if (
            isinstance(detail_snap, dict)
            and detail_snap.get("version") == 1
            and str(detail_snap.get("quiz_kind") or "").lower() == "qcm"
        ):
            detail_snap, score_final = recompute_qcm_snapshot_v1(detail_snap)

        row = TestEcrit(
            id=uuid.uuid4(),
            id_candidature=body.id_candidature,
            score_ecrit=score_final,
            # Règle actuelle centralisée ici ; tout déclenchement oral lit ``row.status_reussite``.
            status_reussite=score_final >= 70,
            detail_snapshot=detail_snap,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        if row.status_reussite is True:
            try:
                oral_ok = ensure_oral_access_and_maybe_email(db, body.id_candidature)
                if not oral_ok:
                    logger.warning(
                        "submit_test_result: test écrit enregistré avec status_reussite=True mais "
                        "préparation de l'accès oral ou envoi de l'email d'invitation oral a échoué "
                        "ou est incomplet pour candidature_id=%s — consulter les logs "
                        "ensure_oral_access_and_maybe_email (DB, SMTP ou email candidat).",
                        body.id_candidature,
                    )
            except Exception:
                db.rollback()
                logger.exception(
                    "Post test écrit : erreur inattendue préparation oral (candidature %s)",
                    body.id_candidature,
                )

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


@router.get("/quiz/results/{candidature_id}")
def get_written_quiz_results(
    candidature_id: UUID,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """
    Rapport test écrit pour le dashboard entreprise (JWT entreprise).
    Les réponses détaillées reposent sur ``tests_ecrits.detail_snapshot`` (soumissions récentes).
    """
    require_plan(db, entreprise, "TRIAL")
    return build_written_quiz_report_payload(db, candidature_id, entreprise.id)
