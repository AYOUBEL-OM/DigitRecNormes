"""
Construction du rapport test écrit (dashboard entreprise) à partir de ``tests_ecrits``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.test_ecrit import TestEcrit
from app.services.qcm_normalization import (
    candidate_answer_display,
    correct_answer_display,
    qcm_answers_equivalent,
    qcm_correction_debug_payload,
)

logger = logging.getLogger(__name__)


def _epreuve_label_from_offre(raw: Optional[str]) -> str:
    if not raw or not str(raw).strip():
        return "Test écrit"
    r = str(raw).strip().lower()
    if "exercice" in r:
        return "Exercice"
    if "qcm" in r:
        return "QCM"
    return str(raw).strip()


def _final_message(status_ok: bool) -> str:
    return "Test réussi" if status_ok else "Test non réussi"


def _normalize_qcm_items(snap: dict[str, Any]) -> list[dict[str, Any]]:
    qcm = snap.get("qcm")
    if not isinstance(qcm, dict):
        return []
    items = qcm.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        opts = it.get("options") if isinstance(it.get("options"), list) else []
        exp = it.get("expected_answer")
        cand = it.get("candidate_answer")
        ok = qcm_answers_equivalent(cand, exp, opts)
        prev = str(it.get("status") or "").lower()
        if ok:
            st = "correct"
        elif prev == "partial":
            st = "partial"
        else:
            st = "incorrect"
        logger.info(
            "QCM CORRECTION DEBUG %s",
            qcm_correction_debug_payload(
                it.get("question_text"),
                cand,
                exp,
                opts,
                ok,
            ),
        )
        out.append(
            {
                "order": int(it.get("order", 0)),
                "question_text": it.get("question_text"),
                "options": opts,
                "expected_answer": exp,
                "candidate_answer": cand,
                "correct_answer_display": correct_answer_display(exp, opts),
                "candidate_answer_display": candidate_answer_display(cand, opts),
                "status": st,
                "score_label": (
                    "1 pt"
                    if ok
                    else ("0.5 pt" if st == "partial" else "0 pt")
                ),
            }
        )
    out.sort(key=lambda x: x["order"])
    return out


def _exercice_block(snap: dict[str, Any]) -> Optional[dict[str, Any]]:
    ex = snap.get("exercice")
    if not isinstance(ex, dict):
        return None
    return {
        "title": ex.get("title"),
        "consigne": ex.get("consigne"),
        "candidate_submission": ex.get("candidate_submission"),
        "evaluation_score": ex.get("evaluation_score"),
        "feedback": ex.get("feedback"),
    }


def _summary_from_snapshot(
    snap: dict[str, Any], score_ecrit: float, status_reussite: bool
) -> dict[str, Any]:
    kind = str(snap.get("quiz_kind") or "").lower()
    if kind == "qcm":
        items = _normalize_qcm_items(snap)
        total = len(items)
        correct = sum(1 for i in items if i["status"] == "correct")
        partial = sum(1 for i in items if i["status"] == "partial")
        incorrect = total - correct - partial
        rate = round((correct / total) * 100) if total else int(round(score_ecrit))
        return {
            "correct_count": correct,
            "incorrect_count": max(0, incorrect),
            "partial_count": partial,
            "success_rate_percent": rate,
            "final_message": _final_message(status_reussite),
        }
    if kind == "exercice":
        return {
            "correct_count": None,
            "incorrect_count": None,
            "partial_count": None,
            "success_rate_percent": int(round(score_ecrit)),
            "final_message": _final_message(status_reussite),
        }
    return {
        "correct_count": None,
        "incorrect_count": None,
        "partial_count": None,
        "success_rate_percent": int(round(score_ecrit)),
        "final_message": _final_message(status_reussite),
    }


def build_written_quiz_report_payload(
    db: Session,
    candidature_id: UUID,
    entreprise_id: UUID,
) -> dict[str, Any]:
    row = (
        db.query(Candidature, Offre)
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(
            Candidature.id == candidature_id,
            Offre.entreprise_id == entreprise_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidature introuvable.",
        )

    _, offre = row
    te = (
        db.query(TestEcrit)
        .filter(TestEcrit.id_candidature == candidature_id)
        .order_by(desc(TestEcrit.id))
        .first()
    )

    base: dict[str, Any] = {
        "candidature_id": str(candidature_id),
        "offre_titre": offre.title,
        "epreuve_type": _epreuve_label_from_offre(offre.type_examens_ecrit),
        "test_present": te is not None,
    }

    if not te:
        base["score_ecrit"] = None
        base["status_reussite"] = None
        base["detail_available"] = False
        base["questions"] = []
        base["exercice"] = None
        base["summary"] = None
        return base

    snap = te.detail_snapshot if isinstance(te.detail_snapshot, dict) else None
    detail_available = bool(snap and snap.get("version") == 1)

    if detail_available and snap is not None:
        kind = str(snap.get("quiz_kind") or "").lower()
        if snap.get("offre_title"):
            base["offre_titre"] = snap["offre_title"]
        base["epreuve_type"] = "QCM" if kind == "qcm" else "Exercice" if kind == "exercice" else base["epreuve_type"]
        questions = _normalize_qcm_items(snap) if kind == "qcm" else []
        ex_block = _exercice_block(snap) if kind == "exercice" else None
        summary = _summary_from_snapshot(snap, float(te.score_ecrit), bool(te.status_reussite))
    else:
        questions = []
        ex_block = None
        summary = {
            "correct_count": None,
            "incorrect_count": None,
            "partial_count": None,
            "success_rate_percent": int(round(float(te.score_ecrit))),
            "final_message": _final_message(bool(te.status_reussite)),
        }

    base["score_ecrit"] = float(te.score_ecrit)
    base["status_reussite"] = bool(te.status_reussite)
    base["detail_available"] = detail_available
    base["detail_missing_hint"] = (
        None
        if detail_available
        else "Les réponses détaillées ne sont pas disponibles pour ce passage (test antérieur à l’enregistrement du détail)."
    )
    base["questions"] = questions
    base["exercice"] = ex_block
    base["summary"] = summary
    return base
