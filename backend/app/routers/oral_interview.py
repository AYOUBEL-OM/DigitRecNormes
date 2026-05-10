"""
Entretien oral — logique absorbée depuis l'ancien dossier Test_orale.

Routes sous préfixe /api/oral (inclus dans main avec prefix="/api").
"""
from __future__ import annotations

import base64
import logging
import random
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import get_settings, resolve_upload_dir
from app.constants.oral_timing import max_answer_seconds_with_margin
from app.core.auth import get_candidat_from_token, get_entreprise_from_token
from app.database import SessionLocal, get_db
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral
from app.services.oral_proctoring import (
    apply_proctoring_event,
    ensure_oral_proctoring_fields,
    normalize_proctoring_flags,
)
from app.services.oral_questions_service import (
    load_or_create_questions_for_test_oral,
    persist_emergency_fallback_questions,
)
from app.services.oral_answer_analysis import transcribe_audio
from app.services.oral_session_finalize import finalize_oral_session_analysis
from app.services.oral_report_service import (
    append_snapshot,
    build_enterprise_report_payload,
    build_pdf_bytes,
    oral_report_download_filename,
)
from app.services.offre_public_access import offre_est_expiree
from app.services.subscription_access import (
    get_entreprise_id_for_oral_session,
    require_plan,
    require_plan_for_entreprise_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oral", tags=["Entretien oral"])

ORAL_SESSION_HEADER = "X-Digitrec-Oral-Token"


def _resolve_oral_session_token(
    *,
    header_token: str | None = None,
    body_token: str | None = None,
    form_token: str | None = None,
    path_token: str | None = None,
) -> str:
    """Jeton de session oral (`tests_oraux.candidate_access_token`), pas le JWT app."""
    for t in (header_token, body_token, form_token):
        if t and str(t).strip():
            return str(t).strip()
    if path_token and str(path_token).strip():
        return str(path_token).strip()
    raise HTTPException(
        status_code=401,
        detail=(
            "Jeton d'accès entretien manquant. "
            f"Utilisez l'en-tête {ORAL_SESSION_HEADER} ou le champ access_token."
        ),
    )


def _require_test_oral_for_authenticated_candidate(
    db: Session,
    oral_token: str,
    candidat: Candidat,
    *,
    allow_completed: bool = False,
) -> tuple[TestOral, Offre]:
    """
    Vérifie : token oral → test_oral → candidature → même candidat JWT ;
    offre active, non expirée.

    Par défaut, refuse ``status == completed`` (flux question / save-answer).
    ``allow_completed=True`` pour ``/finalize-analysis`` : l’entretien est marqué
    terminé dès la dernière réponse enregistrée, puis l’analyse doit pouvoir tourner.
    """
    oral = (
        db.query(TestOral)
        .filter(TestOral.candidate_access_token == oral_token.strip())
        .first()
    )
    if not oral:
        raise HTTPException(
            status_code=404,
            detail="Lien d'entretien invalide ou expiré.",
        )

    cand = (
        db.query(Candidature)
        .filter(Candidature.id == oral.id_candidature)
        .first()
    )
    if not cand:
        raise HTTPException(status_code=404, detail="Candidature introuvable.")

    if cand.candidat_id != candidat.id:
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas autorisé à accéder à cet entretien oral.",
        )

    offre = db.query(Offre).filter(Offre.id == cand.offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable.")

    st = (offre.status or "").strip().lower()
    if st != "active":
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas autorisé à accéder à cet entretien oral.",
        )

    if offre_est_expiree(offre):
        raise HTTPException(
            status_code=403,
            detail="L'offre associée à cet entretien n'est plus accessible (date limite dépassée).",
        )

    oral_st = (oral.status or "").strip().lower()
    if oral_st == "completed" and not allow_completed:
        raise HTTPException(
            status_code=403,
            detail="Cet entretien oral est déjà terminé.",
        )
    if oral_st == "completed" and allow_completed:
        print("FINALIZE allowed even if status=completed", flush=True)

    return oral, offre


def _require_test_oral_for_session_magic_link(
    db: Session,
    oral_token: str,
    *,
    allow_completed: bool = True,
) -> tuple[TestOral, Offre]:
    """
    Charge ``TestOral`` + ``Offre`` à partir du seul ``candidate_access_token`` (lien d’invitation).

    Utilisé par ``POST /proctoring-event`` : pas de JWT requis. La possession du secret de
    session oral suffit (même modèle de confiance qu’un lien magique). Évite les 403 fréquents
    lorsque le JWT candidat (stockage app, refresh, autre onglet) ne correspond pas exactement
    à la candidature, ou lorsque ``require_plan_for_entreprise_id`` bloque pour un motif billing.

    ``allow_completed=True`` : derniers heartbeats / ``session_end`` après la dernière réponse
    ne sont pas rejetés (statut peut déjà être ``completed``).
    """
    tok = oral_token.strip()
    print(
        "PROCTORING-AUTH: magic-link token",
        {
            "token_len": len(tok),
            "token_prefix": (tok[:12] + "…") if len(tok) > 12 else tok,
        },
        flush=True,
    )

    oral = (
        db.query(TestOral)
        .filter(TestOral.candidate_access_token == tok)
        .first()
    )
    if not oral:
        print("PROCTORING-AUTH: FAIL unknown oral token", flush=True)
        raise HTTPException(
            status_code=404,
            detail="Lien d'entretien invalide ou expiré.",
        )

    cand = (
        db.query(Candidature)
        .filter(Candidature.id == oral.id_candidature)
        .first()
    )
    if not cand:
        print("PROCTORING-AUTH: FAIL missing candidature", {"oral_id": str(oral.id)}, flush=True)
        raise HTTPException(status_code=404, detail="Candidature introuvable.")

    offre = db.query(Offre).filter(Offre.id == cand.offre_id).first()
    if not offre:
        print("PROCTORING-AUTH: FAIL missing offre", {"oral_id": str(oral.id)}, flush=True)
        raise HTTPException(status_code=404, detail="Offre introuvable.")

    st = (offre.status or "").strip().lower()
    if st != "active":
        print(
            "PROCTORING-AUTH: FAIL offre not active",
            {"oral_id": str(oral.id), "offre_status": offre.status},
            flush=True,
        )
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas autorisé à accéder à cet entretien oral.",
        )

    if offre_est_expiree(offre):
        print("PROCTORING-AUTH: FAIL offre expired", {"oral_id": str(oral.id)}, flush=True)
        raise HTTPException(
            status_code=403,
            detail="L'offre associée à cet entretien n'est plus accessible (date limite dépassée).",
        )

    oral_st = (oral.status or "").strip().lower()
    if oral_st == "completed" and not allow_completed:
        print("PROCTORING-AUTH: FAIL oral completed", {"oral_id": str(oral.id)}, flush=True)
        raise HTTPException(
            status_code=403,
            detail="Cet entretien oral est déjà terminé.",
        )

    print(
        "PROCTORING-AUTH: OK",
        {
            "oral_id": str(oral.id),
            "oral_status": oral.status,
            "candidature_id": str(cand.id),
            "allow_completed": allow_completed,
        },
        flush=True,
    )
    return oral, offre


def _oral_bootstrap_payload(db: Session, offre: Offre, oral: TestOral) -> dict[str, Any]:
    if offre.entreprise_id:
        require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")
    return {
        "titre_poste": offre.title or "",
        "departement": offre.profile or None,
        "nombre_questions_oral": offre.nombre_questions_orale,
        "candidate_photo_uploaded": bool((oral.candidate_photo_url or "").strip()),
    }


class GenerateOralQuestionsBody(BaseModel):
    """Charge ou génère les questions pour le test oral (session identifiée par Bearer)."""

    model_config = ConfigDict(extra="ignore")

    access_token: Optional[str] = None  # compat : préférer Authorization: Bearer
    job_title: str = ""
    keywords: str = ""
    nb_tech: Optional[int] = None


class ProctoringEventBody(BaseModel):
    """Événement proctoring : authentification par ``candidate_access_token`` uniquement (pas de JWT)."""

    model_config = ConfigDict(extra="ignore")

    access_token: Optional[str] = None  # ou en-tête X-Digitrec-Oral-Token
    event_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UploadCandidatePhotoBody(BaseModel):
    """Photo d’identité avant début des questions (JPEG base64)."""

    model_config = ConfigDict(extra="ignore")

    image_base64: str = ""
    access_token: Optional[str] = None


def _recordings_dir() -> Path:
    root = resolve_upload_dir(get_settings().ORAL_RECORDINGS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _oral_answers_dir() -> Path:
    root = resolve_upload_dir(get_settings().ORAL_ANSWERS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _oral_snapshots_dir() -> Path:
    root = resolve_upload_dir(get_settings().ORAL_SNAPSHOTS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _oral_photos_dir() -> Path:
    root = resolve_upload_dir(get_settings().ORAL_PHOTOS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.get("/bootstrap")
def oral_bootstrap_bearer(
    candidat: Candidat = Depends(get_candidat_from_token),
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    db: Session = Depends(get_db),
):
    """
    Contexte page entretien : JWT candidat (`Authorization: Bearer`) + jeton de session oral
    (`X-Digitrec-Oral-Token` = `candidate_access_token`).
    """
    oral_tok = _resolve_oral_session_token(header_token=x_digitrec_oral_token)
    oral, offre = _require_test_oral_for_authenticated_candidate(db, oral_tok, candidat)
    return _oral_bootstrap_payload(db, offre, oral)


@router.get("/bootstrap/{access_token}")
def oral_bootstrap_path_legacy(
    access_token: str,
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """Compat : token oral dans le chemin ; JWT candidat obligatoire dans Authorization."""
    oral_tok = _resolve_oral_session_token(path_token=access_token)
    oral, offre = _require_test_oral_for_authenticated_candidate(db, oral_tok, candidat)
    return _oral_bootstrap_payload(db, offre, oral)


@router.get("/offre-summary/{offre_id}")
def get_offre_summary_for_oral(offre_id: UUID, db: Session = Depends(get_db)):
    """
    Données nécessaires à la page d'entretien oral (évite l'accès Supabase direct depuis le frontend).
    `offre_id` : UUID de la ligne `offres` (même usage que l'ancien lien /interview/:token).
    """
    offre = (
        db.query(Offre)
        .filter(Offre.id == offre_id, Offre.status == "active")
        .first()
    )
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable ou inactive.")

    if offre.entreprise_id:
        require_plan_for_entreprise_id(db, offre.entreprise_id, "TRIAL")

    return {
        "titre_poste": offre.title or "",
        "departement": offre.profile or None,
        "nombre_questions_oral": offre.nombre_questions_orale,
    }


@router.post("/proctoring-event")
def post_proctoring_event(
    body: ProctoringEventBody,
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    db: Session = Depends(get_db),
):
    """
    Enregistre un indicateur proctoring (onglet, plein écran, visage, regard, etc.).
    Met à jour les colonnes `tests_oraux` existantes + JSON `cheating_flags` (dont `summary_global`).

    **Auth** : uniquement le jeton de session oral (``X-Digitrec-Oral-Token`` ou ``access_token`` JSON).
    Aucun JWT candidat requis — évite les 403 liés au couple JWT + lien ou à l’abonnement entreprise.
    """
    token = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        body_token=body.access_token,
    )
    oral, _offre = _require_test_oral_for_session_magic_link(
        db,
        token,
        allow_completed=True,
    )
    _ = _offre
    print(
        "PROCTORING-AUTH: applying event",
        {
            "oral_id": str(oral.id),
            "event_type": body.event_type,
        },
        flush=True,
    )
    try:
        out = apply_proctoring_event(
            db,
            oral,
            body.event_type,
            body.metadata or {},
        )
    except Exception as exc:
        logger.exception("proctoring-event: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Impossible d'enregistrer l'événement proctoring.",
        ) from exc

    print(
        "PROCTORING-AUTH: event stored",
        {
            "oral_id": str(oral.id),
            "event_type": body.event_type,
            "ok": out.get("ok"),
            "tab_switch_count": out.get("tab_switch_count"),
        },
        flush=True,
    )

    if not out.get("ok"):
        return out
    return {"status": "ok", **out}


@router.post("/generate-ai-questions")
async def generate_questions(
    body: GenerateOralQuestionsBody,
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """
    Retourne les questions pour l'entretien oral : lecture `oral_test_questions` si déjà
    enregistrées pour ce `tests_oraux`, sinon génération structurée (3 fixes + banques
    domaine/niveau depuis l’offre) puis persistance.
    """
    token = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        body_token=body.access_token,
    )
    oral, _offre = _require_test_oral_for_authenticated_candidate(db, token, candidat)
    _ = _offre
    eid = get_entreprise_id_for_oral_session(db, oral)
    require_plan_for_entreprise_id(db, eid, "TRIAL")

    try:
        questions, source = load_or_create_questions_for_test_oral(
            db,
            oral,
            body.job_title,
            body.keywords,
            body.nb_tech,
        )
    except Exception as exc:
        logger.exception("generate-ai-questions: échec chargement ou génération — %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            questions, source = persist_emergency_fallback_questions(
                db,
                oral,
                body.job_title,
                body.keywords,
                body.nb_tech,
            )
        except Exception as fb_exc:
            logger.exception(
                "generate-ai-questions: fallback d'urgence impossible — %s", fb_exc
            )
            try:
                db.rollback()
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail="Impossible de préparer les questions d'entretien.",
            ) from fb_exc

    return {
        "questions": questions,
        "total_count": len(questions),
        "source": source,
    }


@router.post("/upload-candidate-photo")
def upload_candidate_photo(
    body: UploadCandidatePhotoBody,
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """
    Photo d’identité obligatoire avant l’entretien : JPEG en base64, JWT candidat + jeton oral.
    Fichier : ``uploads/oral_photos/{test_oral_id}.jpg`` ; URL dans ``tests_oraux.candidate_photo_url``.
    """
    tok = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        body_token=body.access_token,
    )
    oral, _offre = _require_test_oral_for_authenticated_candidate(db, tok, candidat)
    _ = _offre
    eid = get_entreprise_id_for_oral_session(db, oral)
    require_plan_for_entreprise_id(db, eid, "TRIAL")

    b64 = (body.image_base64 or "").strip()
    if b64.startswith("data:"):
        parts = b64.split(",", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Image base64 invalide (data URL).")
        b64 = parts[1].strip()
    if not b64:
        raise HTTPException(status_code=400, detail="Image manquante.")

    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Décodage base64 impossible.") from exc

    if len(raw) > 3_500_000:
        raise HTTPException(status_code=400, detail="Image trop volumineuse.")
    if len(raw) < 1024:
        raise HTTPException(status_code=400, detail="Image trop petite ou corrompue.")
    if not raw.startswith(b"\xff\xd8\xff"):
        raise HTTPException(
            status_code=400,
            detail="Format JPEG attendu (capture depuis la page d’entretien).",
        )

    dest_dir = _oral_photos_dir()
    fname = f"{oral.id}.jpg"
    path = dest_dir / fname
    try:
        path.write_bytes(raw)
    except OSError as exc:
        logger.exception("upload-candidate-photo: écriture fichier")
        raise HTTPException(status_code=500, detail="Échec enregistrement fichier.") from exc

    rel = f"/uploads/oral_photos/{fname}"
    oral.candidate_photo_url = rel
    db.add(oral)
    db.commit()
    return {"status": "success", "candidate_photo_url": rel}


@router.post("/save-answer")
async def save_answer(
    audio: UploadFile = File(...),
    access_token: Optional[str] = Form(default=None),
    question_order: int = Form(...),
    answer_duration_seconds: Optional[int] = Form(None),
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """
    Enregistre l’audio et les métadonnées (durée) — **sans** analyse IA (transcription / scores en fin de session).
    `question_order` : 1-based, aligné sur `question_order` en base.
    JWT candidat dans `Authorization` ; jeton oral via `X-Digitrec-Oral-Token` ou champ `access_token`.
    """
    tok = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        form_token=access_token,
    )
    oral, _offre = _require_test_oral_for_authenticated_candidate(db, tok, candidat)
    _ = _offre
    eid = get_entreprise_id_for_oral_session(db, oral)
    require_plan_for_entreprise_id(db, eid, "TRIAL")

    st = (oral.status or "").strip().lower()
    if st != "completed":
        oral.status = "in_progress"

    row = (
        db.query(OralTestQuestion)
        .filter(
            OralTestQuestion.test_oral_id == oral.id,
            OralTestQuestion.question_order == int(question_order),
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Question introuvable pour cet entretien.",
        )

    dest_dir = _oral_answers_dir()
    ext = Path(audio.filename or "answer.webm").suffix or ".webm"
    safe = f"{oral.id}_{int(question_order)}_{uuid.uuid4().hex[:12]}{ext}"
    path = dest_dir / safe

    print("SAVE_ANSWER START", flush=True)
    print("SAVE_ANSWER ABS_PATH:", str(path.resolve()), flush=True)
    print("SAVE_ANSWER ORAL_ANSWERS_ROOT:", str(dest_dir.resolve()), flush=True)
    logger.info(
        "save-answer: start oral_id=%s question_order=%s filename=%s",
        str(oral.id),
        int(question_order),
        audio.filename,
    )
    try:
        with path.open("wb") as f:
            shutil.copyfileobj(audio.file, f)
    except Exception as exc:
        logger.exception("save-answer: file write failed")
        raise HTTPException(status_code=500, detail="Échec enregistrement audio.") from exc
    finally:
        print("SAVE_ANSWER FILE_SAVED", flush=True)

    size = path.stat().st_size
    duration = int(answer_duration_seconds) if answer_duration_seconds and answer_duration_seconds > 0 else max(
        1, min(300, size // 16000)
    )

    max_allowed = max_answer_seconds_with_margin(int(question_order), row.question_text or "")
    if duration > max_allowed:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"Durée de réponse refusée ({duration}s > {max_allowed}s autorisées avec marge).",
        )

    rel_url = f"/uploads/oral_answers/{safe}"
    row.audio_url = rel_url
    row.answer_duration_seconds = duration
    row.transcript_text = None
    row.hesitation_score = None
    row.relevance_score = None

    # Horodatage session : secours si session_start / session_end (proctoring) n’ont pas été reçus (réseau, etc.).
    if oral.started_at is None:
        oral.started_at = datetime.now(timezone.utc)

    max_order = (
        db.query(func.max(OralTestQuestion.question_order))
        .filter(OralTestQuestion.test_oral_id == oral.id)
        .scalar()
    )
    if max_order is not None and int(question_order) == int(max_order):
        oral.finished_at = datetime.now(timezone.utc)
        if oral.started_at is not None:
            oral.duration_seconds = max(
                0,
                int((oral.finished_at - oral.started_at).total_seconds()),
            )
        oral.status = "completed"

    ensure_oral_proctoring_fields(oral)
    db.add(row)
    db.add(oral)
    db.commit()
    print("SAVE_ANSWER COMMIT_DONE", flush=True)

    return {
        "status": "success",
        "question_order": int(question_order),
        "audio_url": rel_url,
        "answer_duration_seconds": duration,
        "pending_analysis": True,
    }


@router.post("/finalize-analysis")
def finalize_oral_analysis(
    access_token: Optional[str] = Form(default=None),
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """
    Lance l’analyse IA agrégée (transcription + un appel LLM) **après** la fin de l’entretien.
    Exécution **synchrone** pour fiabilité (transcription + scores persistés avant la réponse).

    La session SQLAlchemy ``work_db`` est dédiée à cette requête : toute la chaîne
    (transcription par question avec commits, agrégat, scores) s’exécute sur cette session.
    """
    print("FINALIZE ENDPOINT CALLED", flush=True)
    logger.info("finalize-analysis: endpoint invoked")
    tok = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        form_token=access_token,
    )
    print("FINALIZE AUTH CANDIDAT:", getattr(candidat, "id", None), flush=True)
    print("FINALIZE ORAL TOKEN PRESENT:", bool(tok and str(tok).strip()), flush=True)
    oral, _offre = _require_test_oral_for_authenticated_candidate(
        db, tok, candidat, allow_completed=True
    )
    _ = _offre
    print("FINALIZE STATUS:", getattr(oral, "status", None), flush=True)
    print("FINALIZE TEST_ORAL_ID:", oral.id, flush=True)
    print("FINALIZE CANDIDATURE_ID:", oral.id_candidature, flush=True)
    eid = get_entreprise_id_for_oral_session(db, oral)
    require_plan_for_entreprise_id(db, eid, "TRIAL")
    work_db = SessionLocal()
    try:
        print("FINALIZE SERVICE START", flush=True)
        out = finalize_oral_session_analysis(work_db, oral.id)
        print("FINALIZE SERVICE RESULT:", out, flush=True)
        if not out.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=out.get("error", "Analyse finale impossible."),
            )
        return out
    except HTTPException:
        raise
    except Exception as exc:
        print("FINALIZE ENDPOINT ERROR:", repr(exc), flush=True)
        logger.exception("finalize-analysis: échec oral_id=%s", oral.id)
        try:
            work_db.rollback()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Échec de l'analyse finale : {exc}",
        ) from exc
    finally:
        work_db.close()


@router.get("/debug/transcription-question/{question_id}")
def debug_transcription_question(
    question_id: UUID,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Diagnostic entreprise : localise l’audio d’une ligne ``oral_test_questions``,
    affiche taille / durée DB et exécute la même chaîne ASR que la finalize (avec ``attempts_log``).
    """
    require_plan(db, entreprise, "TRIAL")
    row = (
        db.query(OralTestQuestion, TestOral, Candidature, Offre)
        .join(TestOral, OralTestQuestion.test_oral_id == TestOral.id)
        .join(Candidature, TestOral.id_candidature == Candidature.id)
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(
            OralTestQuestion.id == question_id,
            Offre.entreprise_id == entreprise.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Question orale introuvable ou non autorisée pour cette entreprise.",
        )
    qrow, _oral, _cand, _offre = row
    rel_url = (qrow.audio_url or "").strip()
    answers_root = resolve_upload_dir(get_settings().ORAL_ANSWERS_DIR)
    name = rel_url.rstrip("/").split("/")[-1] if rel_url else ""
    path = answers_root / name if name else Path("")
    dur = int(qrow.answer_duration_seconds or 60)
    size_b = path.stat().st_size if path.is_file() else 0
    outcome = transcribe_audio(
        path,
        get_settings(),
        dur,
        qrow.question_text or "",
    )
    return {
        "oral_test_question_id": str(question_id),
        "question_order": qrow.question_order,
        "audio_url": qrow.audio_url,
        "audio_path_resolved": str(path.resolve()) if name else None,
        "file_exists": path.is_file(),
        "file_size_bytes": size_b,
        "duration_seconds_db": qrow.answer_duration_seconds,
        "transcription_text": outcome.text,
        "transcription_source": outcome.source,
        "attempts_log": outcome.attempts_log,
    }


def _load_oral_for_entreprise(
    db: Session,
    candidature_id: UUID,
    entreprise,
) -> tuple[Candidature, Offre, Optional[TestOral], list[OralTestQuestion]]:
    row = (
        db.query(Candidature, Offre)
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(
            Candidature.id == candidature_id,
            Offre.entreprise_id == entreprise.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Candidature introuvable.")
    candidature, offre = row
    test_oral = (
        db.query(TestOral)
        .filter(TestOral.id_candidature == candidature_id)
        .order_by(desc(TestOral.id))
        .first()
    )
    if not test_oral:
        return candidature, offre, None, []
    q_rows = (
        db.query(OralTestQuestion)
        .filter(OralTestQuestion.test_oral_id == test_oral.id)
        .order_by(OralTestQuestion.question_order.asc())
        .all()
    )
    return candidature, offre, test_oral, q_rows


@router.get("/results/{candidature_id}/pdf")
def get_oral_results_pdf(
    candidature_id: UUID,
    refresh_ai: bool = Query(False, description="Régénérer le résumé IA et le badge"),
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """Rapport oral au format PDF (dashboard entreprise)."""
    require_plan(db, entreprise, "TRIAL")
    _, offre, test_oral, q_rows = _load_oral_for_entreprise(db, candidature_id, entreprise)
    if not test_oral:
        raise HTTPException(status_code=404, detail="Aucun entretien oral pour cette candidature.")
    try:
        payload = build_enterprise_report_payload(
            db, test_oral, q_rows, offre.title, candidature_id, refresh_ai
        )
        pdf = build_pdf_bytes(offre.title, str(candidature_id), payload)
        fname = oral_report_download_filename(str(candidature_id), payload)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("oral results pdf: génération échouée candidature_id=%s", candidature_id)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc!r}") from exc


@router.get("/export-pdf")
def export_oral_pdf_compat(
    candidature_id: UUID = Query(..., description="ID candidature"),
    refresh_ai: bool = Query(False, description="Régénérer le résumé IA et le badge"),
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """Alias compat: /api/oral/export-pdf?candidature_id=..."""
    return get_oral_results_pdf(
        candidature_id=candidature_id,
        refresh_ai=refresh_ai,
        entreprise=entreprise,
        db=db,
    )


@router.get("/results/{candidature_id}")
def get_oral_results(
    candidature_id: UUID,
    refresh_ai: bool = Query(False, description="Régénérer le résumé IA et le badge"),
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Rapport entretien oral (dashboard entreprise) : questions, scores, proctoring,
    timeline, badge, synthèse IA (cache JSON), snapshot principal.
    """
    require_plan(db, entreprise, "TRIAL")
    print("REPORT ENDPOINT HIT", {"candidature_id": str(candidature_id), "refresh_ai": bool(refresh_ai)}, flush=True)
    _, offre, test_oral, q_rows = _load_oral_for_entreprise(db, candidature_id, entreprise)

    if not test_oral:
        return {
            "candidature_id": str(candidature_id),
            "offre_titre": offre.title,
            "test_oral": None,
            "questions": [],
            "badge": None,
            "ai_summary": None,
            "timeline": [],
            "primary_snapshot_url": None,
            "candidate_photo_url": None,
            "candidate_image_url": None,
        }

    return build_enterprise_report_payload(
        db, test_oral, q_rows, offre.title, candidature_id, refresh_ai
    )


@router.post("/snapshot")
async def upload_oral_snapshot(
    access_token: Optional[str] = Form(default=None),
    reason: str = Form("interval"),
    image: UploadFile = File(...),
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """
    Capture caméra candidat (JWT + jeton oral). Stockage fichier + URL dans `cheating_flags.snapshots`.
    """
    tok = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        form_token=access_token,
    )
    oral, _offre = _require_test_oral_for_authenticated_candidate(db, tok, candidat)
    _ = _offre
    eid = get_entreprise_id_for_oral_session(db, oral)
    require_plan_for_entreprise_id(db, eid, "TRIAL")

    content_type = (image.content_type or "").lower()
    if content_type not in ("image/jpeg", "image/jpg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=400,
            detail="Format image non supporté (jpeg, png, webp).",
        )

    raw = await image.read()
    if len(raw) > 3_500_000:
        raise HTTPException(status_code=400, detail="Image trop volumineuse.")

    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"

    dest_dir = _oral_snapshots_dir()
    safe = f"{oral.id}_{uuid.uuid4().hex[:12]}{ext}"
    path = dest_dir / safe
    path.write_bytes(raw)

    rel = f"/uploads/oral_snapshots/{safe}"
    local_image_path = path
    ex = local_image_path.is_file()
    sz = int(local_image_path.stat().st_size) if ex else None
    print(
        "SNAPSHOT RECEIVED",
        {
            "oral_id": str(oral.id),
            "rel_url": rel,
            "local_image_path": str(local_image_path.resolve()),
            "exists": ex,
            "size": sz,
            "reason": reason[:80] or "interval",
        },
        flush=True,
    )
    try:
        append_snapshot(
            db,
            oral,
            rel,
            reason[:80] or "interval",
            local_image_path=local_image_path,
        )
        print(
            "SNAPSHOT STORED:",
            {"oral_id": str(oral.id), "url": rel, "reason": reason[:80]},
            flush=True,
        )
    except Exception as exc:
        logger.exception("oral snapshot: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Impossible d'enregistrer la capture.",
        ) from exc
    return {"status": "ok", "url": rel}


@router.post("/finalize-interview")
async def finalize_interview(
    file: UploadFile = File(...),
    access_token: Optional[str] = Form(default=None),
    question_text: Optional[str] = Form(None),
    x_digitrec_oral_token: str | None = Header(default=None, alias=ORAL_SESSION_HEADER),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    """Ancienne route de dépôt audio (compatibilité). Préférer POST /save-answer."""
    _ = question_text
    tok = _resolve_oral_session_token(
        header_token=x_digitrec_oral_token,
        form_token=access_token,
    )
    oral, _offre = _require_test_oral_for_authenticated_candidate(db, tok, candidat)
    _ = _offre

    dest_dir = _recordings_dir()
    safe_name = f"{oral.id_candidature}_{random.randint(100, 999)}.webm"
    path = dest_dir / safe_name

    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"status": "success"}
