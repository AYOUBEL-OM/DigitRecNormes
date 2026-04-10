"""
Service d'analyse CV par IA (Groq).
"""
import json
import logging
import os
from typing import Any, Dict

import fitz
from groq import Groq
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.candidat import Candidat
from app.models.candidature import Candidature, StatutCandidature
from app.models.offre import Offre
from app.services.email_service import send_acceptance_email, send_rejection_email

logger = logging.getLogger(__name__)
settings = get_settings()


def _extract_text_from_pdf(cv_path: str) -> str:
    """Extrait le texte brut d'un PDF via PyMuPDF."""
    chunks = []
    with fitz.open(cv_path) as doc:
        for page in doc:
            chunks.append(page.get_text("text"))
    return "\n".join(chunks).strip()


def _build_job_context(db: Session, offre_id: Any) -> Dict[str, Any]:
    """Récupère les exigences de l'offre pour construire le prompt."""
    offre = db.query(Offre).filter(Offre.id == offre_id).first()
    if not offre:
        raise ValueError("Offre introuvable pour le filtrage CV.")

    return {
        "title": offre.title or "",
        "profile": offre.profile or "",
        "niveau_etude": offre.niveau_etude or offre.level or "",
        "nombre_experience_minimun": offre.nombre_experience_minimun or 0,
        "competences_requises": offre.competences or "",
    }


def _parse_json_response(raw_content: str) -> Dict[str, Any]:
    """Tolère une réponse textuelle contenant un JSON embarqué."""
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(raw_content[start : end + 1])


def analyze_cv_with_groq(cv_text: str, requirements: Dict[str, Any]) -> Dict[str, Any]:
    """Compare CV vs exigence poste via Groq (Llama 3.1 70B)."""
    api_key = os.getenv("GROQ_API_KEY")
    model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    if not api_key:
        raise ValueError("GROQ_API_KEY n'est pas configurée.")

    system_prompt = (
        "Tu es un expert en recrutement. "
        "Analyse le CV par rapport aux exigences d'une offre. "
        "Réponds uniquement avec un objet JSON valide contenant exactement les clés: "
        "score (0-100), report (texte concis), decision (Potential|Under-qualified|Perfect Match)."
    )
    user_prompt = (
        "EXIGENCES OFFRE:\n"
        f"{json.dumps(requirements, ensure_ascii=False, indent=2)}\n\n"
        "TEXTE CV:\n"
        f"{cv_text[:16000]}\n\n"
        "Retourne strictement un JSON valide."
    )

    client = Groq(api_key=api_key)
    try:
        completion = client.chat.completions.create(
            model=model_name,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = (completion.choices[0].message.content or "").strip()
        if not content:
            raise RuntimeError("Réponse Groq vide.")
    except Exception as exc:
        raise RuntimeError(f"Erreur appel Groq: {exc}") from exc

    return _parse_json_response(content)


def _compute_status(score: float) -> StatutCandidature:
    if score < 50:
        return StatutCandidature.refusee
    return StatutCandidature.acceptee


def run_cv_filtering_for_candidature(candidature_id: Any, offre_id: Any, cv_abs_path: str) -> None:
    """
    Exécute le screening CV et persiste le résultat en base.
    Fonction pensée pour FastAPI BackgroundTasks.
    """
    db = SessionLocal()
    try:
        cv_text = _extract_text_from_pdf(cv_abs_path)
        requirements = _build_job_context(db, offre_id)
        ai_result = analyze_cv_with_groq(cv_text=cv_text, requirements=requirements)

        score = float(ai_result.get("score", 0))
        report = str(ai_result.get("report", "")).strip()
        decision = str(ai_result.get("decision", "")).strip()
        if decision:
            report = f"Decision IA: {decision}\n{report}".strip()

        candidature = db.query(Candidature).filter(Candidature.id == candidature_id).first()
        if not candidature:
            logger.warning("Candidature %s introuvable pour screening CV.", candidature_id)
            return

        candidature.score_cv_matching = score
        candidature.cv_analysis_report = report
        candidature.statut = _compute_status(score)

        # Le schéma DB peut contenir etape_actuelle même si non mappé ORM.
        columns = {col["name"] for col in inspect(db.bind).get_columns("candidatures")}
        if "etape_actuelle" in columns:
            db.execute(
                text("UPDATE candidatures SET etape_actuelle = :etape WHERE id = :cid"),
                {"etape": "CV_Screening", "cid": str(candidature_id)},
            )

        db.commit()

        candidat = db.query(Candidat).filter(Candidat.id == candidature.candidat_id).first()
        job_title = requirements.get("title") or "ce poste"
        candidat_name = "Candidat"
        candidat_email = None
        if candidat:
            candidat_name = f"{candidat.prenom} {candidat.nom}".strip() or "Candidat"
            candidat_email = candidat.email

        if candidat_email:
            if candidature.statut == StatutCandidature.acceptee:
                send_acceptance_email(
                    candidat_email=candidat_email,
                    candidat_name=candidat_name,
                    job_title=job_title,
                )
            elif candidature.statut == StatutCandidature.refusee:
                send_rejection_email(
                    candidat_email=candidat_email,
                    candidat_name=candidat_name,
                    job_title=job_title,
                    ai_analysis_report=report,
                )
        else:
            logger.warning(
                "Email candidat introuvable pour candidature %s, notification ignorée.",
                candidature_id,
            )
    except Exception:
        db.rollback()
        logger.exception("Echec du filtrage CV IA pour candidature %s", candidature_id)
    finally:
        db.close()
