"""
Analyse agrégée de fin d’entretien oral : transcription + un seul appel LLM (Groq) pour pertinence,
niveau de langue et synthèse soft skills — après que le candidat a quitté le flux question par question.

Scores finaux (global, confiance, stress) : ``oral_answer_analysis.compute_oral_score`` appelle
``compute_oral_global_score`` (scoring v4, détail dans ``session_scores.score_breakdown``).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from uuid import UUID

from groq import APIError, Groq, RateLimitError
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings, resolve_upload_dir
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral
from app.services.oral_answer_analysis import (
    TRANSCRIPTION_FAILED_MARKER,
    _is_mock_transcript,
    _is_transcription_failed_marker,
    apply_batch_relevance_to_analysis,
    analyze_answer_row,
    compute_oral_score,
)
from app.services.oral_insights_storage import insight_blob_from_analysis, set_answer_insight
from app.services.oral_proctoring import ensure_oral_proctoring_fields, normalize_proctoring_flags

logger = logging.getLogger(__name__)

ORAL_BATCH_LLM_MODEL = "llama3-8b-8192"


def _commit_question_fallback(
    db: Session,
    row: OralTestQuestion,
    qtext: str,
    reason_suffix: str,
    prepared: list[dict[str, Any]],
) -> None:
    """Après log d’erreur : évite transcript/scores NULL et alimente ``prepared`` pour l’agrégat."""
    detail = f"{TRANSCRIPTION_FAILED_MARKER} {reason_suffix}".strip()[:12000]
    row.transcript_text = detail
    row.hesitation_score = 50.0
    row.relevance_score = 50.0
    print("TRANSCRIPT_COMMIT_START row=", row.id, "fallback", flush=True)
    db.add(row)
    db.commit()
    print("TRANSCRIPT_COMMITTED row=", row.id, "fallback", flush=True)
    try:
        db.refresh(row)
    except Exception:
        pass
    analysis_fb: dict[str, Any] = {
        "transcript": detail,
        "hesitation_score": 50.0,
        "relevance_score": 50.0,
    }
    prepared.append(
        {
            "question_order": int(row.question_order),
            "question": qtext,
            "transcript": detail,
            "analysis": analysis_fb,
            "row": row,
        }
    )


def _groq_api_key() -> str:
    return (os.getenv("GROQ_API_KEY") or get_settings().GROQ_API_KEY or "").strip()


def _groq_json_completion(messages: list[dict[str, str]]) -> str:
    """Un appel JSON avec repli exponentiel sur 429."""
    api_key = _groq_api_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquant pour l'analyse agrégée.")
    delays_sec = [0, 2, 6, 12]
    last_rl: RateLimitError | None = None
    client = Groq(api_key=api_key)
    for i, delay in enumerate(delays_sec):
        if delay:
            time.sleep(delay)
        try:
            completion = client.chat.completions.create(
                model=ORAL_BATCH_LLM_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.15,
                max_tokens=2048,
            )
            raw = (completion.choices[0].message.content or "").strip()
            if not raw:
                raise RuntimeError("Réponse LLM vide.")
            return raw
        except RateLimitError as e:
            last_rl = e
            logger.warning(
                "oral_session_finalize: RateLimitError (tentative %s/%s) — %s",
                i + 1,
                len(delays_sec),
                e,
            )
            continue
        except APIError as e:
            logger.exception("oral_session_finalize: APIError Groq")
            raise RuntimeError(str(e)) from e
    raise RuntimeError("Quota Groq dépassé pour l'analyse agrégée.") from last_rl


def _name_context_for_row(db: Session, oral: TestOral, question_text: str) -> dict[str, Any] | None:
    try:
        candature = (
            db.query(Candidature)
            .options(
                joinedload(Candidature.candidat),
                joinedload(Candidature.offre).joinedload(Offre.entreprise),
            )
            .filter(Candidature.id == oral.id_candidature)
            .first()
        )
        if candature and candature.candidat and candature.offre:
            cand = candature.candidat
            offre = candature.offre
            nom_p = (cand.nom or "").strip()
            prenom = (cand.prenom or "").strip()
            return {
                "candidate_name": f"{nom_p} {prenom}".strip(),
                "job_title": (offre.title or "").strip(),
                "city": (offre.localisation or "").strip(),
                "company_name": (offre.entreprise.nom or "").strip()
                if offre.entreprise
                else "",
                "question_text": question_text,
            }
    except Exception as exc:
        logger.warning("oral_session_finalize: contexte noms — %s", exc)
    return None


def _build_batch_prompt(pairs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for p in pairs:
        lines.append(
            f"--- Question {p['question_order']} ---\n"
            f"Énoncé : {p['question']}\n"
            f"Transcription : {p['transcript']}\n"
        )
    body = "\n".join(lines)
    return (
        "Tu es un évaluateur RH expert. Analyse l'entretien oral suivant (questions et transcriptions).\n"
        "Réponds par UN SEUL objet JSON (sans markdown) avec exactement ces clés :\n"
        "- per_question : liste d'objets { \"question_order\": entier, \"relevance\": nombre entre 0 et 100 } "
        "(une entrée par question, même ordre que ci-dessous)\n"
        "- language_level_global : une phrase en français (niveau CECRL estimé + langue dominante)\n"
        "- soft_skills_summary : un paragraphe court en français (communication, clarté, assurance perçue)\n"
        "Sois réaliste et nuancé.\n\n"
        f"{body}"
    )


def _parse_batch_json(raw: str) -> dict[str, Any]:
    raw_s = (raw or "").strip()
    try:
        data = json.loads(raw_s)
    except json.JSONDecodeError as e:
        logger.warning("oral_session_finalize: json.loads échec batch — %s", e)
        raise ValueError(f"JSON batch invalide: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON racine attendu.")
    return data


def _heuristic_batch_fallback(prepared: list[dict[str, Any]]) -> dict[str, Any]:
    """Si Groq agrégé échoue : pertinence par question depuis l’analyse locale déjà calculée."""
    per_question: list[dict[str, Any]] = []
    for p in prepared:
        o = int(p["question_order"])
        rel = float((p.get("analysis") or {}).get("relevance_score") or 0.0)
        per_question.append({"question_order": o, "relevance": max(0.0, min(100.0, rel))})
    return {
        "per_question": per_question,
        "language_level_global": (
            "Estimation locale (LLM agrégé indisponible) : voir transcriptions et scores par question."
        ),
        "soft_skills_summary": (
            "Synthèse locale : communication et clarté déduites des indicateurs calculés sur chaque réponse."
        ),
    }


def _apply_batch_blob_to_vars(
    blob: dict[str, Any],
) -> tuple[dict[int, float], str | None, str | None]:
    batch_relevance: dict[int, float] = {}
    for item in blob.get("per_question") or []:
        if not isinstance(item, dict):
            continue
        try:
            o = int(item.get("question_order"))
            r = float(item.get("relevance"))
            batch_relevance[o] = max(0.0, min(100.0, r))
        except (TypeError, ValueError):
            continue
    lang_global = str(blob.get("language_level_global") or "").strip() or None
    soft_summary = str(blob.get("soft_skills_summary") or "").strip() or None
    return batch_relevance, lang_global, soft_summary


def finalize_oral_session_analysis(db: Session, test_oral_id: UUID) -> dict[str, Any]:
    """
    Transcrit (si besoin via analyze_answer_row), appelle un seul LLM d'agrégation,
    met à jour les lignes et ``compute_oral_score`` sans second appel LLM « niveau langue » session.
    """
    print("FINALIZE START test_oral_id=", test_oral_id, flush=True)
    try:
        return _finalize_oral_session_analysis_body(db, test_oral_id)
    except Exception as e:
        print("FINALIZE ERROR:", str(e), flush=True)
        logger.exception("oral_session_finalize: FINALIZE ERROR")
        try:
            db.rollback()
        except Exception:
            pass
        raise


def _finalize_oral_session_analysis_body(db: Session, test_oral_id: UUID) -> dict[str, Any]:
    oral = db.query(TestOral).filter(TestOral.id == test_oral_id).first()
    if not oral:
        return {"ok": False, "error": "test_oral introuvable"}

    rows = (
        db.query(OralTestQuestion)
        .filter(OralTestQuestion.test_oral_id == test_oral_id)
        .order_by(OralTestQuestion.question_order.asc())
        .all()
    )
    if not rows:
        return {"ok": False, "error": "aucune question"}

    answers_root = resolve_upload_dir(get_settings().ORAL_ANSWERS_DIR)
    print("FINALIZE QUESTIONS COUNT:", len(rows), flush=True)
    for r in rows:
        tx_preview = r.transcript_text
        if tx_preview and len(str(tx_preview)) > 200:
            tx_preview = str(tx_preview)[:200] + "…"
        print(
            "FINALIZE ROW",
            r.id,
            r.question_order,
            r.audio_url,
            tx_preview,
            flush=True,
        )
    print("FINALIZE ANSWERS ROOT:", answers_root, flush=True)

    def _row_fully_analyzed(r: OralTestQuestion) -> bool:
        tx = (r.transcript_text or "").strip()
        if not tx or _is_transcription_failed_marker(tx) or _is_mock_transcript(tx):
            return False
        return r.hesitation_score is not None and r.relevance_score is not None

    if rows and all(_row_fully_analyzed(r) for r in rows):
        print("FINALIZE SKIP_SESSION_ALREADY_ANALYZED", flush=True)
        score_error: str | None = None
        try:
            compute_oral_score(db, test_oral_id, skip_session_language_llm=True)
        except Exception as score_exc:
            print("FINALIZE ERROR (compute_oral_score):", str(score_exc), flush=True)
            logger.exception("compute_oral_score après finalize (session déjà analysée)")
            score_error = str(score_exc)
        result_early: dict[str, Any] = {
            "ok": True,
            "test_oral_id": str(test_oral_id),
            "questions_processed": len(rows),
            "already_analyzed": True,
            "batch_llm": False,
            "batch_llm_fallback_used": False,
            "compute_oral_score_error": score_error,
        }
        print("FINALIZE END result=", result_early, flush=True)
        return result_early

    # Phase 1 — après upload audio (save-answer) uniquement : transcription ASR + écriture DB par question.
    # Un commit par ligne garantit que transcript_text est persisté même si l’agrégat LLM échoue ensuite.
    prepared: list[dict[str, Any]] = []
    for row in rows:
        qtext = row.question_text or ""
        try:
            existing_tx = (row.transcript_text or "").strip()
            if (
                existing_tx
                and not _is_transcription_failed_marker(existing_tx)
                and not _is_mock_transcript(existing_tx)
            ):
                print(
                    "FINALIZE SKIP_ROW_ALREADY_HAS_TRANSCRIPT row=",
                    row.id,
                    "order=",
                    row.question_order,
                    flush=True,
                )
                hes = float(row.hesitation_score) if row.hesitation_score is not None else 0.0
                rel = float(row.relevance_score) if row.relevance_score is not None else 0.0
                analysis_existing: dict[str, Any] = {
                    "transcript": existing_tx,
                    "hesitation_score": hes,
                    "relevance_score": rel,
                }
                prepared.append(
                    {
                        "question_order": int(row.question_order),
                        "question": qtext,
                        "transcript": existing_tx,
                        "analysis": analysis_existing,
                        "row": row,
                    }
                )
                continue

            if not row.audio_url:
                logger.warning(
                    "oral_session_finalize: pas d'audio pour question_order=%s — fallback DB",
                    row.question_order,
                )
                print(
                    "FINALIZE QUESTION ERROR row=",
                    row.id,
                    "pas d'audio_url — fallback",
                    flush=True,
                )
                _commit_question_fallback(
                    db,
                    row,
                    qtext,
                    "(aucun audio_url après save-answer)",
                    prepared,
                )
                continue
            rel_url = str(row.audio_url).strip()
            name = rel_url.rstrip("/").split("/")[-1]
            path = answers_root / name
            print(
                "FINALIZE AUDIO PATH:",
                path,
                "EXISTS:",
                path.exists(),
                "IS_FILE:",
                path.is_file(),
                flush=True,
            )
            if not path.is_file():
                logger.error(
                    "oral_session_finalize: fichier audio manquant — %s (root=%s)",
                    path,
                    answers_root,
                )
                print(
                    "FINALIZE QUESTION ERROR row=",
                    row.id,
                    f"fichier manquant rel={rel_url!r} resolved={path!r}",
                    flush=True,
                )
                _commit_question_fallback(
                    db,
                    row,
                    qtext,
                    f"(fichier audio introuvable sur disque: {path})",
                    prepared,
                )
                continue

            dur = int(row.answer_duration_seconds or 60)
            ctx = _name_context_for_row(db, oral, qtext)

            print(
                "TRANSCRIBE_START oral_test_question_id="
                f"{row.id} test_oral_id={test_oral_id} question_order={row.question_order} audio_path={path}",
                flush=True,
            )
            analysis = analyze_answer_row(
                qtext,
                dur,
                audio_path=path,
                name_context=ctx,
                relevance_use_llm=False,
            )
            transcript = str(analysis.get("transcript") or "")
            rel_val = float(analysis.get("relevance_score") or 0.0)
            print(
                "TRANSCRIPT_RESULT oral_test_question_id="
                f"{row.id} question_order={row.question_order} len={len(transcript)}",
                flush=True,
            )
            _log_tx = (
                transcript
                if len(transcript) <= 2000
                else f"{transcript[:2000]}… [suite tronquée pour le log, len={len(transcript)}]"
            )
            print(f"transcript_text={_log_tx!r}", flush=True)
            print(f"Relevance (heuristic): {rel_val}", flush=True)

            row.transcript_text = transcript
            row.answer_duration_seconds = dur
            row.hesitation_score = float(analysis.get("hesitation_score") or 0.0)
            row.relevance_score = rel_val
            print("TRANSCRIPT_COMMIT_START row=", row.id, flush=True)
            db.add(row)
            db.commit()
            print(
                "TRANSCRIPT_COMMITTED oral_test_question_id="
                f"{row.id} question_order={row.question_order}",
                flush=True,
            )
            try:
                db.refresh(row)
            except Exception:
                pass

            prepared.append(
                {
                    "question_order": int(row.question_order),
                    "question": qtext,
                    "transcript": transcript,
                    "analysis": analysis,
                    "row": row,
                }
            )
        except Exception as row_exc:
            print("FINALIZE QUESTION ERROR row=", row.id, repr(row_exc), flush=True)
            logger.exception(
                "oral_session_finalize: échec ligne question_order=%s",
                getattr(row, "question_order", "?"),
            )
            try:
                db.rollback()
            except Exception:
                pass
            r2 = db.query(OralTestQuestion).filter(OralTestQuestion.id == row.id).first()
            if r2:
                try:
                    _commit_question_fallback(
                        db,
                        r2,
                        qtext,
                        f"(exception transcription/analyse: {row_exc!r})",
                        prepared,
                    )
                except Exception as fb_exc:
                    print(
                        "FINALIZE FALLBACK_COMMIT_ERROR row=",
                        getattr(r2, "id", None),
                        repr(fb_exc),
                        flush=True,
                    )
                    logger.exception("oral_session_finalize: échec fallback après erreur ligne")
            continue

    if not prepared:
        return {"ok": False, "error": "aucune réponse audio exploitable"}

    batch_relevance: dict[int, float] = {}
    lang_global: str | None = None
    soft_summary: str | None = None
    batch_llm_ok = False

    try:
        user_prompt = _build_batch_prompt(
            [
                {
                    "question_order": p["question_order"],
                    "question": p["question"],
                    "transcript": p["transcript"][:12000],
                }
                for p in prepared
            ]
        )
        raw_json = _groq_json_completion(
            [
                {
                    "role": "system",
                    "content": "Tu réponds uniquement par un objet JSON valide, en français pour les champs texte.",
                },
                {"role": "user", "content": user_prompt},
            ]
        )
        blob = _parse_batch_json(raw_json)
        batch_relevance, lang_global, soft_summary = _apply_batch_blob_to_vars(blob)
        batch_llm_ok = True
    except Exception as exc:
        logger.exception("oral_session_finalize: échec LLM agrégé — %s", exc)
        fb = _heuristic_batch_fallback(prepared)
        batch_relevance, lang_global, soft_summary = _apply_batch_blob_to_vars(fb)

    flags = normalize_proctoring_flags(oral.cheating_flags)

    for p in prepared:
        order = p["question_order"]
        analysis: dict[str, Any] = dict(p["analysis"])
        row: OralTestQuestion = p["row"]
        rel_override = batch_relevance.get(order, float(analysis.get("relevance_score") or 0.0))
        merged = apply_batch_relevance_to_analysis(
            analysis,
            rel_override,
            row.question_text or "",
            str(analysis.get("transcript") or ""),
        )
        row.relevance_score = float(merged.get("relevance_score") or 0.0)
        row.hesitation_score = float(merged.get("hesitation_score") or 0.0)
        row.transcript_text = str(merged.get("transcript") or row.transcript_text or "")

        set_answer_insight(flags, order, insight_blob_from_analysis(merged))
        db.add(row)

    oral.cheating_flags = flags
    ensure_oral_proctoring_fields(oral)
    db.add(oral)
    db.commit()

    score_error: str | None = None
    try:
        compute_oral_score(db, oral.id, skip_session_language_llm=True)
    except Exception as score_exc:
        print("FINALIZE ERROR (compute_oral_score):", str(score_exc), flush=True)
        logger.exception("compute_oral_score après finalize")
        score_error = str(score_exc)

    oral2 = db.query(TestOral).filter(TestOral.id == test_oral_id).first()
    if oral2 is not None:
        if lang_global:
            oral2.language_level_global = lang_global[:2000]
        if soft_summary:
            oral2.soft_skills_summary = soft_summary[:4000]
        db.add(oral2)
        db.commit()

    result: dict[str, Any] = {
        "ok": True,
        "test_oral_id": str(test_oral_id),
        "questions_processed": len(prepared),
        "batch_llm": batch_llm_ok,
        "batch_llm_fallback_used": not batch_llm_ok,
        "compute_oral_score_error": score_error,
    }
    print("FINALIZE END result=", result, flush=True)
    return result
