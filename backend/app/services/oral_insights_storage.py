"""
Métadonnées d’analyse oral sans colonnes SQL dédiées : stockage dans `tests_oraux.cheating_flags` (JSONB).

Clés réservées (rétrocompatibles avec le reste du JSON proctoring) :
- answer_insights : { "<question_order>": { ... } }
- session_scores : agrégats recalculés (communication_avg, technical_avg, final_decision, …)
"""
from __future__ import annotations

from typing import Any

ANSWER_INSIGHTS_KEY = "answer_insights"
SESSION_SCORES_KEY = "session_scores"


def ensure_insights_branch(flags: dict[str, Any]) -> None:
    raw = flags.get(ANSWER_INSIGHTS_KEY)
    if not isinstance(raw, dict):
        flags[ANSWER_INSIGHTS_KEY] = {}


def set_answer_insight(flags: dict[str, Any], question_order: int, payload: dict[str, Any]) -> None:
    ensure_insights_branch(flags)
    flags[ANSWER_INSIGHTS_KEY][str(int(question_order))] = payload


def get_answer_insight(flags: dict[str, Any], question_order: int) -> dict[str, Any] | None:
    raw = (flags.get(ANSWER_INSIGHTS_KEY) or {}).get(str(int(question_order)))
    return raw if isinstance(raw, dict) else None


def insight_blob_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Sous-ensemble sérialisable pour JSONB (pas de transcript complet : déjà en base)."""
    return {
        "transcript_language": analysis.get("transcript_language"),
        "transcript_language_raw": analysis.get("transcript_language_raw"),
        "transcript_confidence": analysis.get("transcript_confidence"),
        "coherence_score": analysis.get("coherence_score"),
        "clarity_score": analysis.get("clarity_score"),
        "language_quality_score": analysis.get("language_quality_score"),
        "confidence_score": analysis.get("confidence_score"),
        "final_answer_score": analysis.get("final_answer_score"),
        "is_correct": analysis.get("is_correct"),
        "evaluation_comment": analysis.get("evaluation_comment"),
        "transcription_source": analysis.get("transcription_source"),
    }
