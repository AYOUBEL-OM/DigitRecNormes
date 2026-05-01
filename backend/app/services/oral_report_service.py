"""
Rapport entretien oral (dashboard entreprise) : enrichissement JSON, badge, résumé IA, PDF.
Réutilise `tests_oraux` / `oral_test_questions` et `cheating_flags` (snapshots, cache IA, `summary_global`).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings, resolve_upload_dir
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral
from app.services.oral_answer_analysis import (
    _normalize_cefr,
    _qualitative_level_from_index,
    analyze_transcript_only,
    compute_text_coherence_score,
    is_incoherent_gibberish_transcript,
)
from app.services.oral_insights_storage import get_answer_insight, insight_blob_from_analysis
from app.services.oral_proctoring import (
    ensure_oral_proctoring_fields,
    get_proctoring_summary_text,
    normalize_proctoring_flags,
)

logger = logging.getLogger(__name__)

# Version du cache `enterprise_report_ai` (régénère si inférieur ou champs manquants).
AI_REPORT_SCHEMA_VERSION = 4

EVENT_LABELS_FR: dict[str, str] = {
    "visibility_hidden": "Perte de visibilité de la page",
    "fullscreen_exit": "Sortie du plein écran",
    "suspicious_motion": "Mouvement atypique",
    "phone_suspected": "Indicateur type téléphone",
    "multi_face": "Plusieurs visages",
    "presence_anomaly": "Visage absent ou instable",
    "heartbeat": "Contrôle présence",
    "session_start": "Début de session",
    "session_end": "Fin de session",
}


def _composite_quality_score(pertinence: float, hesitation: float, coherence: float) -> float:
    """Pondération demandée : pertinence, fluidité (100 - hésitation), cohérence textuelle."""
    return float(
        max(
            0.0,
            min(
                100.0,
                pertinence * 0.5 + (100.0 - hesitation) * 0.2 + coherence * 0.3,
            ),
        )
    )


def quality_label(
    relevance: Optional[float],
    hesitation: Optional[float],
    _legacy_final_answer_score: Optional[float] = None,
    *,
    transcript: Optional[str] = None,
    coherence_score: Optional[float] = None,
) -> str:
    """
    bonne | moyenne | faible — aligné sur pertinence, hésitation et cohérence textuelle.
    ``_legacy_final_answer_score`` est ignoré (ancien agrégat qui faussait le libellé « Qualité »).
    """
    if relevance is None:
        return "faible"
    rel_f = float(relevance)
    hes = float(hesitation) if hesitation is not None else 40.0
    coh = (
        float(coherence_score)
        if coherence_score is not None
        else compute_text_coherence_score(transcript or "")
    )
    gib = is_incoherent_gibberish_transcript(transcript or "", coh, rel_f)

    if gib:
        return "faible"
    if rel_f < 40.0 or coh < 40.0:
        return "faible"
    if rel_f > 70.0 and hes < 48.0 and coh >= 65.0:
        return "bonne"
    if 40.0 <= rel_f <= 70.0 and coh >= 40.0:
        return "moyenne"
    if rel_f > 70.0:
        return "moyenne"
    return "faible"


def confidence_label(score: Optional[float]) -> str:
    if score is None:
        return "Non estimé"
    if score >= 72:
        return "Confiant"
    if score >= 52:
        return "Modéré"
    return "Réservé"


def stress_label(score: Optional[float]) -> str:
    if score is None:
        return "Non estimé"
    if score < 38:
        return "Stress faible"
    if score < 62:
        return "Stress modéré"
    return "Stress élevé"


def language_display(level: Optional[str]) -> str:
    if level and str(level).strip():
        return str(level).strip()
    return "Non évalué automatiquement"


_CEFR_IN_TEXT_RE = re.compile(r"\b(A1|A2|B1|B2|C1|C2)\b", re.I)
_CEFR_ORDER_MAP = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}


def normalize_confidence_stress(
    confidence: Optional[float],
    stress: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Cohérence affichage : stress très bas n’implique pas une confiance très basse, et inversement.
    Règles métier (couche correction) — ne modifie pas la base, uniquement les valeurs « rapport ».
    """
    if confidence is None and stress is None:
        return None, None
    c = float(confidence) if confidence is not None else 52.0
    s = float(stress) if stress is not None else 40.0
    if not (math.isfinite(c) and math.isfinite(s)):
        return confidence, stress
    c = max(0.0, min(100.0, c))
    s = max(0.0, min(100.0, s))
    # Zone contradictoire typique : stress très bas + confiance très basse → rehausser les deux.
    if s <= 30.0 and c < 40.0:
        c = max(c, 55.0)
        s = max(s, 45.0)
    for _ in range(6):
        changed = False
        if s <= 30.0 and c < 50.0:
            nc = max(c, 55.0)
            if abs(nc - c) > 1e-6:
                c = nc
                changed = True
        if c < 40.0 and s < 40.0:
            ns = max(s, 45.0)
            if abs(ns - s) > 1e-6:
                s = ns
                changed = True
        if not changed:
            break
    return round(c, 2), round(s, 2)


def extract_cefr_from_language_text(text: Optional[str]) -> Optional[str]:
    """Extrait A1..C2 depuis `language_level_global` (ex. « Niveau oral : B1 … »)."""
    if not text or not str(text).strip():
        return None
    m = _CEFR_IN_TEXT_RE.search(str(text))
    if not m:
        return None
    return _normalize_cefr(m.group(1))


def resolve_niveau_linguistique_final(
    language_level_global: Optional[str],
    language_proficiency_index: Any,
) -> str:
    """
    Source de vérité unique CECRL pour le rapport (alignée backend, pas sur l’IA synthèse).
    1) niveau présent dans le texte agrégé `language_level_global`
    2) sinon indice agrégé `language_proficiency_index` → table CECRL
    """
    from_text = extract_cefr_from_language_text(language_level_global)
    if from_text:
        return from_text
    if isinstance(language_proficiency_index, (int, float)) and not isinstance(language_proficiency_index, bool):
        try:
            _, cefr = _qualitative_level_from_index(float(language_proficiency_index))
            return _normalize_cefr(cefr)
        except (TypeError, ValueError):
            pass
    return "B1"


def _cefr_tokens_in_string(s: str) -> set[str]:
    return {_normalize_cefr(m.group(1)) for m in _CEFR_IN_TEXT_RE.finditer(str(s or ""))}


def _text_contradicts_cefr_level(text: str, final_cefr: str) -> bool:
    """True si le texte affirme un niveau CECRL différent du niveau final (ex. C1 dans le texte, B1 final)."""
    tokens = _cefr_tokens_in_string(text)
    if not tokens:
        return False
    fi = _CEFR_ORDER_MAP.get(_normalize_cefr(final_cefr), 2)
    for t in tokens:
        ti = _CEFR_ORDER_MAP.get(t, fi)
        if ti != fi:
            return True
    return False


def _strength_template_for_cefr(cefr: str) -> str:
    """Phrase factuelle liée au seul repère CECRL (pas d’invention LLM)."""
    lines = {
        "A1": "Communication très élémentaire mais identifiable.",
        "A2": "Échanges simples avec repères compréhensibles malgré des limites.",
        "B1": "Communication globalement compréhensible.",
        "B2": "Communication structurée avec une bonne clarté d’ensemble.",
        "C1": "Communication fluide avec maîtrise étendue du lexique.",
        "C2": "Communication très aboutie, proche d’un usage maîtrisé.",
    }
    c = _normalize_cefr(cefr)
    return lines.get(c, lines["B1"])


def _strength_template_for_confidence(conf: float) -> Optional[str]:
    if conf >= 70:
        return "Bonne aisance à l’oral (confiance agrégée élevée)."
    if conf >= 52:
        return "Aisance à l’oral modérée (confiance agrégée correcte)."
    return None


def _apply_ai_report_coherence(
    ai: dict[str, Any],
    oral: TestOral,
    flags: dict[str, Any],
) -> dict[str, Any]:
    """
    Post-traitement rapport IA : niveau linguistique unique, points forts alignés métriques,
    filtrage des phrases LLM contradictoires (CECRL), scores confiance/stress cohérents pour le contexte.
    """
    ss = flags.get("session_scores") if isinstance(flags.get("session_scores"), dict) else {}
    nivel = resolve_niveau_linguistique_final(
        oral.language_level_global,
        ss.get("language_proficiency_index"),
    )
    conf_n, stress_n = normalize_confidence_stress(oral.confidence_score, oral.stress_score)
    conf_f = float(conf_n) if conf_n is not None else 0.0

    lang_line = f"Bon niveau linguistique ({nivel}) — {_strength_template_for_cefr(nivel)}"
    conf_line = _strength_template_for_confidence(conf_f)

    uniq = _UniqueText()
    ordered: list[str] = []
    x = uniq.add(lang_line)
    if x:
        ordered.append(x)
    if conf_line:
        y = uniq.add(conf_line)
        if y:
            ordered.append(y)

    for s in _str_list(ai.get("strengths")):
        if _text_contradicts_cefr_level(s, nivel):
            continue
        z = uniq.add(s)
        if z:
            ordered.append(z)
        if len(ordered) >= 4:
            break

    if not ordered:
        ordered = [lang_line]

    weaknesses_in = _str_list(ai.get("weaknesses"))
    weaknesses_out: list[str] = []
    wuniq = _UniqueText()
    for s in weaknesses_in:
        if _text_contradicts_cefr_level(s, nivel):
            continue
        u = wuniq.add(s)
        if u:
            weaknesses_out.append(u)
        if len(weaknesses_out) >= 4:
            break
    if not weaknesses_out:
        weaknesses_out = [
            "Points de vigilance à confirmer en entretien direct (agrégats techniques uniquement)."
        ]

    out = dict(ai)
    out["strengths"] = ordered[:4]
    out["weaknesses"] = weaknesses_out[:4]
    out["niveau_linguistique_final"] = nivel
    out["confidence_score_report"] = conf_n
    out["stress_score_report"] = stress_n
    return out


def answer_correctness_label(
    insight: Optional[dict[str, Any]],
    relevance: Optional[float],
) -> str:
    """Indication prudente : correcte | partielle | hors_sujet | non évalué."""
    if insight and insight.get("is_correct") is True:
        return "correcte"
    if relevance is not None and relevance >= 40:
        return "partielle"
    if relevance is not None and relevance < 40:
        return "hors_sujet"
    return "non évalué"


def proctoring_summary_key(oral: TestOral, flags: dict[str, Any]) -> str:
    """stable | suspect | a_verifier"""
    tabs = oral.tab_switch_count or 0
    fs = oral.fullscreen_exit_count or 0
    phone = bool(oral.phone_detected)
    other = bool(oral.other_person_detected)
    pres = bool(oral.presence_anomaly_detected)
    mv = oral.suspicious_movements_count or 0
    est = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
    susp = est.get("suspicion_assessment")
    susp_lvl = ""
    if isinstance(susp, dict):
        susp_lvl = str(susp.get("level") or "").upper()
    if not susp_lvl:
        susp_lvl = str(est.get("suspicion_risk_level") or est.get("cheating_risk_level") or "").upper()
    mv_obj = est.get("movement_analysis")
    mv_label = str(mv_obj.get("label") or "").lower().strip() if isinstance(mv_obj, dict) else ""

    if phone or other or susp_lvl == "HIGH" or tabs >= 6 or fs >= 6 or mv >= 12 or mv_label == "élevé":
        return "suspect"
    if (
        pres
        or susp_lvl == "MEDIUM"
        or mv_label in ("modéré", "élevé")
        or tabs >= 1 and (phone or other or pres or mv >= 4)
        or tabs >= 3
        or fs >= 3
        or mv >= 6
    ):
        return "a_verifier"
    return "stable"


def proctoring_summary_label(key: str) -> str:
    return {
        "stable": "Comportement stable",
        "suspect": "Comportement suspect",
        "a_verifier": "À vérifier",
    }.get(key, "À vérifier")


def heuristic_badge(oral: TestOral, questions: list[OralTestQuestion]) -> dict[str, str]:
    """Badge sans LLM : excellent_candidat | bon_candidat | a_surveiller."""
    score = oral.score_oral_global
    stress = oral.stress_score
    tabs = oral.tab_switch_count or 0
    phone = oral.phone_detected
    other = oral.other_person_detected

    if score is None:
        key = "a_surveiller"
    elif score >= 76 and (stress is None or stress < 42) and not phone and not other and tabs < 4:
        key = "excellent_candidat"
    elif score >= 58 and (stress is None or stress < 62) and not phone and not other:
        key = "bon_candidat"
    else:
        key = "a_surveiller"

    labels = {
        "excellent_candidat": "Excellent candidat",
        "bon_candidat": "Bon candidat",
        "a_surveiller": "À surveiller",
    }
    return {"key": key, "label": labels[key], "source": "heuristic"}


def _cache_fingerprint(oral: TestOral, questions: list[OralTestQuestion]) -> str:
    flags = normalize_proctoring_flags(oral.cheating_flags)
    parts = [
        str(oral.score_oral_global),
        str(oral.confidence_score),
        str(oral.stress_score),
        str(oral.tab_switch_count),
        str(oral.phone_detected),
        json.dumps(flags.get("session_scores") or {}, sort_keys=True),
        json.dumps(flags.get("estimates") or {}, sort_keys=True),
    ]
    for q in sorted(questions, key=lambda x: x.question_order):
        parts.append((q.transcript_text or "")[:400])
        parts.append(json.dumps(get_answer_insight(flags, q.question_order) or {}, sort_keys=True))
    parts.append(f"ai_schema_{AI_REPORT_SCHEMA_VERSION}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _fetch_candidate_display_name(db: Session, oral: TestOral) -> str:
    row = (
        db.query(Candidat.prenom, Candidat.nom)
        .join(Candidature, Candidature.candidat_id == Candidat.id)
        .filter(Candidature.id == oral.id_candidature)
        .first()
    )
    if row:
        p, n = row
        name = f"{(p or '').strip()} {(n or '').strip()}".strip()
        if name:
            return name
    return "Candidat"


def _dominant_gaze_direction_label(gaze: dict[str, Any]) -> str:
    """Direction dominante agrégée (heartbeats) pour le prompt IA — pas une frame instantanée."""
    pairs: list[tuple[str, float]] = [
        ("center", float(gaze.get("center_ratio") or 0.0)),
        ("off", float(gaze.get("off_ratio") or 0.0)),
        ("down", float(gaze.get("down_ratio") or 0.0)),
        ("left", float(gaze.get("left_ratio") or 0.0)),
        ("right", float(gaze.get("right_ratio") or 0.0)),
        ("up", float(gaze.get("up_ratio") or 0.0)),
        ("unknown", float(gaze.get("unknown_ratio") or 0.0)),
    ]
    if sum(v for _, v in pairs) <= 0.0001:
        return "unknown"
    return max(pairs, key=lambda x: x[1])[0]


def _suspicion_metrics_for_ai(
    oral: TestOral,
    estimates: dict[str, Any],
) -> tuple[Optional[float], str]:
    susp_a = estimates.get("suspicion_assessment")
    if isinstance(susp_a, dict):
        raw = susp_a.get("score")
        try:
            score = round(float(raw), 2) if raw is not None else None
        except (TypeError, ValueError):
            score = None
        lvl = str(susp_a.get("level") or "").strip().upper()
    else:
        raw2 = estimates.get("suspicion_score")
        try:
            score = round(float(raw2), 2) if raw2 is not None else None
        except (TypeError, ValueError):
            score = None
        lvl = str(estimates.get("cheating_risk_level") or estimates.get("suspicion_risk_level") or "").strip().upper()
    if lvl not in ("LOW", "MEDIUM", "HIGH"):
        lvl = "LOW"
    if score is None:
        score = 0.0
    if bool(oral.phone_detected) or bool(oral.other_person_detected) or bool(oral.presence_anomaly_detected):
        if lvl == "LOW":
            lvl = "MEDIUM"
        score = max(float(score), 25.0)
    return score, lvl


def _build_ai_rich_context(
    db: Session,
    oral: TestOral,
    questions: list[OralTestQuestion],
    job_title: str,
) -> dict[str, Any]:
    flags = normalize_proctoring_flags(oral.cheating_flags)
    gaze = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    estimates = flags.get("estimates") if isinstance(flags.get("estimates"), dict) else {}
    counters = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}

    def _ratio(est_key: str, gaze_key: str) -> float:
        v = estimates.get(est_key)
        if v is None:
            v = gaze.get(gaze_key)
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    rows_payload = build_questions_payload(questions, oral)
    answers: list[dict[str, Any]] = []
    rel_vals: list[float] = []
    hes_vals: list[float] = []
    for r in rows_payload:
        rel = r.get("relevance_score")
        hes = r.get("hesitation_score")
        if isinstance(rel, (int, float)):
            rel_vals.append(float(rel))
        if isinstance(hes, (int, float)):
            hes_vals.append(float(hes))
        answers.append(
            {
                "question": (r.get("question_text") or "")[:500],
                "transcript": ((r.get("transcript_text") or "") or "")[:1200],
                "relevance_score": round(float(rel), 2) if isinstance(rel, (int, float)) else None,
                "hesitation_score": round(float(hes), 2) if isinstance(hes, (int, float)) else None,
                "quality_label": str(r.get("quality_label") or ""),
            }
        )

    avg_rel = round(sum(rel_vals) / len(rel_vals), 2) if rel_vals else None
    avg_hes = round(sum(hes_vals) / len(hes_vals), 2) if hes_vals else None

    session_scores = flags.get("session_scores") if isinstance(flags.get("session_scores"), dict) else {}
    prof_idx = session_scores.get("language_proficiency_index")
    nivel_final = resolve_niveau_linguistique_final(oral.language_level_global, prof_idx)
    conf_rep, stress_rep = normalize_confidence_stress(oral.confidence_score, oral.stress_score)
    conf_for_metrics = conf_rep if conf_rep is not None else oral.confidence_score
    stress_for_metrics = stress_rep if stress_rep is not None else oral.stress_score
    suspicion_score, suspicion_level = _suspicion_metrics_for_ai(oral, estimates)
    gaze_direction = _dominant_gaze_direction_label(gaze)
    anomalies = {
        "presence_anomaly": bool(oral.presence_anomaly_detected),
        "multiple_persons": bool(oral.other_person_detected),
        "phone_detected": bool(oral.phone_detected),
        "any_anomaly": bool(
            oral.presence_anomaly_detected or oral.other_person_detected or oral.phone_detected
        ),
    }
    ai_input_metrics: dict[str, Any] = {
        "score_oral": oral.score_oral_global,
        "confidence_score": conf_for_metrics,
        "stress_score": stress_for_metrics,
        "suspicion_score": suspicion_score,
        "suspicion_level": suspicion_level,
        "gaze_direction": gaze_direction,
        "anomalies": anomalies,
        "niveau_linguistique_final": nivel_final,
        "hesitation_score": avg_hes,
        "average_relevance": avg_rel,
    }

    return {
        "candidate_name": _fetch_candidate_display_name(db, oral),
        "job_title": (job_title or "").strip() or None,
        "score_oral": oral.score_oral_global,
        "score_oral_global": oral.score_oral_global,
        "confidence_score": conf_for_metrics,
        "stress_score": stress_for_metrics,
        "confidence_score_raw": oral.confidence_score,
        "stress_score_raw": oral.stress_score,
        "language_level_global": oral.language_level_global,
        "niveau_linguistique_final": nivel_final,
        "language_proficiency_index": prof_idx,
        "soft_skills_summary": (oral.soft_skills_summary or "").strip() or None,
        "average_relevance": avg_rel,
        "average_hesitation": avg_hes,
        "hesitation_score": avg_hes,
        "suspicion_score": suspicion_score,
        "suspicion_level": suspicion_level,
        "gaze_direction": gaze_direction,
        "anomalies": dict(anomalies),
        "ai_input_metrics": ai_input_metrics,
        "answers": answers[:20],
        "proctoring": {
            "tab_switch_count": int(oral.tab_switch_count or 0),
            "fullscreen_exit_count": int(oral.fullscreen_exit_count or 0),
            "phone_detected": bool(oral.phone_detected),
            "other_person_detected": bool(oral.other_person_detected),
            "presence_anomaly_detected": bool(oral.presence_anomaly_detected),
            "gaze_off_ratio": round(_ratio("gaze_off_ratio", "off_ratio"), 4),
            "gaze_center_ratio": round(_ratio("gaze_center_ratio", "center_ratio"), 4),
            "rapid_motion_heartbeat_count": int(counters.get("rapid_motion_heartbeat_count") or 0),
        },
    }


def _map_synthesis_badge_to_legacy(raw_key: str, oral: TestOral) -> tuple[str, Optional[str]]:
    """Mappe les clés « promising|watch|… » vers le triplet UI existant ; conserve le libellé IA si fourni."""
    k = (raw_key or "").strip().lower()
    score = oral.score_oral_global
    if k == "strong":
        if score is not None and float(score) >= 76:
            return "excellent_candidat", None
        return "bon_candidat", None
    if k == "promising":
        return "bon_candidat", None
    if k in ("watch", "risk", "weak"):
        return "a_surveiller", None
    return "bon_candidat", None


def _str_list(val: Any, *, max_items: int = 8) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val[:max_items]:
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def _norm_insight(s: str) -> str:
    """
    Normalisation légère pour déduplication :
    - minuscule, sans accents
    - ponctuation / espaces normalisés
    - chiffres conservés (signal utile)
    """
    t = str(s or "").strip().lower()
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\u2019’]", "'", t)
    t = re.sub(r"[^a-z0-9\s%/().'\-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _is_similar_insight(a: str, b: str) -> bool:
    na = _norm_insight(a)
    nb = _norm_insight(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.86


class _UniqueText:
    """Collecte de phrases/points uniques (anti-duplication)."""

    def __init__(self) -> None:
        self.used: list[str] = []

    def add(self, s: str) -> str | None:
        t = str(s or "").strip()
        if not t:
            return None
        for u in self.used:
            if _is_similar_insight(t, u):
                return None
        self.used.append(t)
        return t

    def add_many(self, items: list[str], *, limit: int) -> list[str]:
        out: list[str] = []
        for x in items:
            y = self.add(x)
            if y:
                out.append(y)
            if len(out) >= limit:
                break
        return out


def _split_sentences_fr(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if not t:
        return []
    parts = re.split(r"(?<=[.!?])\s+", t)
    return [p.strip() for p in parts if p.strip()]


def _join_sentences(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join([p.strip() for p in parts if p.strip()])).strip()


def _groq_report_json(
    oral: TestOral,
    questions: list[OralTestQuestion],
    proctoring_key: str,
    heuristic: dict[str, str],
    rich_context: dict[str, Any],
) -> Optional[dict[str, Any]]:
    api_key = (os.getenv("GROQ_API_KEY") or "").strip() or (get_settings().GROQ_API_KEY or "").strip()
    if not api_key:
        return None

    model = (get_settings().GROQ_MODEL or "llama-3.1-70b-versatile").strip()

    metrics_json = json.dumps(
        rich_context.get("ai_input_metrics") or {},
        ensure_ascii=False,
        indent=2,
    )
    full_json = json.dumps(rich_context, ensure_ascii=False, indent=2, default=str)
    print("AI INPUT DATA:", full_json[:18000], flush=True)

    prompt = (
        "Tu es un expert RH. Tu produis une analyse UNIQUE pour ce candidat, basée UNIQUEMENT sur les données JSON fournies.\n"
        "Tu DOIS générer une analyse différente dès que les chiffres ou booléens changent (scores, suspicion, regard, anomalies).\n"
        "INTERDIT : phrases génériques réutilisables pour tout candidat, modèles répétitifs, formulations « passe-partout ».\n"
        "INTERDIT : inventer des faits absents du JSON.\n\n"
        "OBLIGATION « ai_input_metrics » : le bloc JSON « ai_input_metrics » (copié ci-dessous) est la source prioritaire. "
        "Dans « summary », tu DOIS intégrer explicitement au moins une fois chacune des valeurs suivantes lorsqu’elles sont présentes : "
        "score_oral, confidence_score, stress_score, suspicion_score, suspicion_level, gaze_direction, niveau_linguistique_final, "
        "hesitation_score (ou null), et l’état des anomalies (presence_anomaly, multiple_persons, phone_detected). "
        "Formule les en style analytique, pas en liste à puces.\n\n"
        "RÈGLES CONDITIONNELLES (à appliquer si les données le justifient ; cite les seuils avec les chiffres réels du JSON) :\n"
        "- Si suspicion_score > 60 : mentionner explicitement une vigilance sur « comportement suspect détecté » (ton professionnel).\n"
        "- Si confidence_score est défini et < 40 : mentionner un « manque d’assurance » à l’oral.\n"
        "- Si gaze_direction est différent de « center » : mentionner un « regard instable » ou « regard majoritairement hors centre ».\n"
        "- Si anomalies.any_anomaly est false ET suspicion_level est LOW : dire explicitement qu’« aucun comportement suspect détecté » "
        "sur la base des indicateurs fournis.\n\n"
        "INTERDICTIONS (formulations) :\n"
        "- Ne pas commencer la synthèse par « Le candidat semble » ni « Il semble que le candidat ».\n"
        "- Éviter : « performance optimale », « dans l’ensemble », « globalement satisfaisant » sans chiffre concret issu du JSON.\n\n"
        "STRUCTURE DES CHAMPS :\n"
        "- « summary » : 3 à 4 phrases maximum, exécutif, ancré dans les métriques (oral + chiffres ci-dessus), sans redondance avec les autres champs.\n"
        "- « strengths » / « weaknesses » : 2 à 4 items chacun, factuels, non redondants entre eux et avec « summary ». "
        "Dans strengths et weaknesses uniquement : éviter les étiquettes CECRL brutes (A1…C2) ; préfère des formulations de compétences. "
        "Dans « summary » : tu peux citer une seule fois le libellé exact de « niveau_linguistique_final » si présent dans le JSON.\n"
        "- « risk_notes » : une phrase courte (risques RH) alignée sur suspicion_score / anomalies.\n"
        "- « visual_behavior », « stress_assessment », « confidence_assessment », « suspicion_assessment » : une phrase chacun, angles distincts, "
        "sans recopier mot pour mot « summary » ou « risk_notes ».\n\n"
        "Réponds UNIQUEMENT par un objet JSON UTF-8 avec les clés exactes :\n"
        "{\n"
        '  "badge_key": "strong" | "promising" | "watch" | "risk" | "weak",\n'
        '  "badge_display": "libellé court en français",\n'
        '  "summary": "3–4 phrases max",\n'
        '  "strengths": ["...", "..."],\n'
        '  "weaknesses": ["...", "..."],\n'
        '  "recommendation": "action RH prudente et concrète",\n'
        '  "decision_reason": "pourquoi ce badge (données chiffrées)",\n'
        '  "risk_notes": "...",\n'
        '  "visual_behavior": "1 phrase — regard",\n'
        '  "stress_assessment": "1 phrase — stress",\n'
        '  "confidence_assessment": "1 phrase — assurance",\n'
        '  "suspicion_assessment": "1 phrase — suspicion / session",\n'
        '  "conclusion": "1 phrase de clôture"\n'
        "}\n\n"
        f"Métriques prioritaires (ai_input_metrics) :\n{metrics_json}\n\n"
        f"Données complètes candidat (JSON) :\n{full_json}\n\n"
        f"Indicateur proctoring agrégé (contexte) : {proctoring_key}\n"
        f"Suggestion heuristique badge legacy : {heuristic.get('key')} / {heuristic.get('label')}\n"
    )

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            temperature=0.42,
            max_tokens=1400,
            messages=[
                {"role": "system", "content": "Tu réponds uniquement par un objet JSON valide."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = (completion.choices[0].message.content or "").strip()
        print("AI OUTPUT:", (raw or "")[:12000], flush=True)
        if not raw:
            return None
        data = json.loads(raw)
        syn_raw = str(data.get("badge_key", "promising")).strip().lower()
        if syn_raw not in ("strong", "promising", "watch", "risk", "weak"):
            syn_raw = "promising"
        legacy_key, _ = _map_synthesis_badge_to_legacy(syn_raw, oral)
        labels_legacy = {
            "excellent_candidat": "Excellent candidat",
            "bon_candidat": "Bon candidat",
            "a_surveiller": "À surveiller",
        }
        display_ia = str(data.get("badge_display") or "").strip()
        badge_display = display_ia or labels_legacy.get(legacy_key, "Profil à analyser")
        strengths = _str_list(data.get("strengths"))
        weaknesses = _str_list(data.get("weaknesses"))
        # Post-traitement anti-duplication : summary + listes + champs texte
        uniq = _UniqueText()
        summary_raw = str(data.get("summary", "")).strip()
        # summary : 3–4 phrases max, sans répétitions internes
        summary_parts = uniq.add_many(_split_sentences_fr(summary_raw), limit=4)
        summary = _join_sentences(summary_parts)

        strengths_u = uniq.add_many(strengths, limit=4)
        weaknesses_u = uniq.add_many(weaknesses, limit=4)

        recommendation = uniq.add(str(data.get("recommendation", "")).strip()) or ""
        decision_reason = uniq.add(str(data.get("decision_reason", "")).strip()) or ""
        risk_notes = uniq.add(str(data.get("risk_notes", "")).strip()) or ""
        visual_behavior = uniq.add(str(data.get("visual_behavior", "")).strip()) or ""
        # Évite la redite systématique : ces champs sont optionnels dans l’UI/PDF
        stress_assessment = uniq.add(str(data.get("stress_assessment", "")).strip()) or ""
        confidence_assessment = uniq.add(str(data.get("confidence_assessment", "")).strip()) or ""
        suspicion_assessment = uniq.add(str(data.get("suspicion_assessment", "")).strip()) or ""
        conclusion = uniq.add(str(data.get("conclusion", "")).strip()) or ""

        return {
            "synthesis_badge_key": syn_raw,
            "badge_key": legacy_key,
            "badge_display": badge_display,
            "summary": summary,
            "strengths": strengths_u,
            "weaknesses": weaknesses_u,
            "recommendation": recommendation,
            "decision_reason": decision_reason,
            "risk_notes": risk_notes,
            "visual_behavior": visual_behavior,
            "stress_assessment": stress_assessment,
            "confidence_assessment": confidence_assessment,
            "suspicion_assessment": suspicion_assessment,
            "conclusion": conclusion,
            "source": "groq",
        }
    except Exception as exc:
        logger.warning("oral_report_service: Groq rapport IA indisponible — %s", exc)
        print("AI OUTPUT:", f"<error> {exc}", flush=True)
        return None


def _deterministic_fallback_report(
    oral: TestOral,
    proctoring_key: str,
    rich_context: dict[str, Any],
    heuristic: dict[str, str],
) -> dict[str, Any]:
    """Synthèse locale sans LLM : varie selon scores et proctoring."""
    score = oral.score_oral_global
    conf_n, stress_n = normalize_confidence_stress(oral.confidence_score, oral.stress_score)
    conf = conf_n if conf_n is not None else oral.confidence_score
    stress = stress_n if stress_n is not None else oral.stress_score
    avg_rel = rich_context.get("average_relevance")
    avg_hes = rich_context.get("average_hesitation")
    proc = rich_context.get("proctoring") or {}
    tabs = int(proc.get("tab_switch_count") or 0)
    fs = int(proc.get("fullscreen_exit_count") or 0)
    phone = bool(proc.get("phone_detected"))
    other = bool(proc.get("other_person_detected"))
    pres = bool(proc.get("presence_anomaly_detected"))
    off_g = float(proc.get("gaze_off_ratio") or 0)
    rapid = int(proc.get("rapid_motion_heartbeat_count") or 0)

    rel_s = f"{float(avg_rel):.1f}" if isinstance(avg_rel, (int, float)) else "N/A"
    hes_s = f"{float(avg_hes):.1f}" if isinstance(avg_hes, (int, float)) else "N/A"
    # Séparation stricte : le proctoring est traité ailleurs (pas dans la synthèse automatique).
    proc_bits: list[str] = []
    if tabs or fs:
        proc_bits.append(f"changements d’onglet {tabs}, sorties plein écran {fs}")
    if phone:
        proc_bits.append("indicateur téléphone")
    if other:
        proc_bits.append("indicateur autre personne")
    if pres:
        proc_bits.append("anomalie de présence")
    if off_g > 0.25:
        proc_bits.append(f"regard hors cadre ({off_g:.0%} estim.)")
    if rapid >= 6:
        proc_bits.append(f"mouvements rapides ({rapid})")
    proc_sentence = ("Signaux proctoring : " + ", ".join(proc_bits) + ".") if proc_bits else ""

    answers = rich_context.get("answers") or []
    first_snippet = ""
    if isinstance(answers, list) and answers:
        tr = str((answers[0].get("transcript") or "")).strip()
        if len(tr) > 160:
            first_snippet = tr[:160].rsplit(" ", 1)[0] + "…"
        else:
            first_snippet = tr

    if score is not None and float(score) >= 75.0:
        opener = f"Score oral global {score:.0f}/100 : réponses globalement alignées avec les attendus."
        tier = "strong"
    elif score is not None and float(score) >= 50.0:
        opener = (
            f"Score oral {score:.0f}/100 : pertinence moyenne ~{rel_s}/100, avec une tenue inégale selon les questions."
        )
        tier = "promising"
    else:
        opener = (
            f"Score oral {score if score is not None else 'N/A'} : réponses souvent partielles, pertinence ~{rel_s}/100."
        )
        tier = "weak"

    if phone or other or proctoring_key == "suspect":
        tier = "risk"
        legacy = "a_surveiller"
    elif tier == "strong" and (float(stress) if stress is not None else 0.0) < 42 and not phone and not other:
        legacy = "excellent_candidat"
    elif tier in ("weak", "risk"):
        legacy = "a_surveiller"
    else:
        legacy = heuristic.get("key") or "bon_candidat"

    uniq = _UniqueText()
    summary = _join_sentences(
        uniq.add_many(
            _split_sentences_fr(
                (f"{opener} " + (f'Extrait : « {first_snippet} ».' if first_snippet else "")).strip()
            ),
            limit=4,
        )
    )

    strengths: list[str] = []
    weaknesses: list[str] = []
    nivel = str(rich_context.get("niveau_linguistique_final") or "").strip() or resolve_niveau_linguistique_final(
        oral.language_level_global,
        rich_context.get("language_proficiency_index"),
    )
    strengths.append(f"Bon niveau linguistique ({nivel}) — {_strength_template_for_cefr(nivel)}")
    if isinstance(avg_rel, (int, float)) and float(avg_rel) >= 55:
        strengths.append(f"Pertinence moyenne élevée (~{rel_s}/100 sur les réponses analysées).")
    if isinstance(avg_hes, (int, float)) and float(avg_hes) <= 45:
        strengths.append(f"Hésitation relativement contenue (~{hes_s}/100).")
    if conf is not None and float(conf) >= 65:
        strengths.append(f"Confiance agrégée {float(conf):.0f}/100 (fluidité + stabilité session).")
    elif conf is not None and float(conf) >= 52:
        tpl = _strength_template_for_confidence(float(conf))
        if tpl:
            strengths.append(tpl)

    if isinstance(avg_rel, (int, float)) and float(avg_rel) < 48:
        weaknesses.append(f"Pertinence moyenne faible (~{rel_s}/100), réponses parfois trop génériques.")
    if isinstance(avg_hes, (int, float)) and float(avg_hes) >= 55:
        weaknesses.append(f"Hésitation marquée (~{hes_s}/100), rythme oral à stabiliser.")
    if stress is not None and float(stress) >= 62:
        weaknesses.append(f"Stress agrégé {float(stress):.0f}/100 : impact possible sur clarté et structure.")

    if not strengths:
        strengths.append("Transcriptions exploitables pour étayer un jugement RH via questions de relance ciblées.")
    if not weaknesses:
        weaknesses.append("Aucun point faible majeur isolé par les agrégats ; confirmer via entretien en direct.")

    strengths = uniq.add_many(strengths, limit=4)
    weaknesses = uniq.add_many(weaknesses, limit=4)

    risk_notes = (
        "Risque RH : signaux de vigilance sur la session (proctoring)."
        if (phone or other or pres or proctoring_key == "suspect")
        else "Pas de signal critique sur les indicateurs automatiques fournis."
    )

    badge_labels = {
        "excellent_candidat": "Excellent candidat",
        "bon_candidat": "Bon candidat",
        "a_surveiller": "À surveiller",
    }
    return {
        "synthesis_badge_key": tier,
        "badge_key": legacy,
        "badge_display": badge_labels.get(legacy, "Profil à analyser"),
        "summary": summary.strip(),
        "strengths": strengths[:4],
        "weaknesses": weaknesses[:4],
        "recommendation": "Prévoir un second échange ciblé (relances sur réponses clés + mise en situation si utile).",
        "decision_reason": "Décision fondée sur scores agrégés et cohérence des réponses (sans nouvel appel IA).",
        "risk_notes": risk_notes,
        "visual_behavior": "",
        "stress_assessment": "",
        "confidence_assessment": "",
        "suspicion_assessment": "",
        "conclusion": badge_labels.get(legacy, "Poursuivre l’analyse humaine."),
        "source": "deterministic_fallback",
        "niveau_linguistique_final": nivel,
        "confidence_score_report": conf_n,
        "stress_score_report": stress_n,
    }


def _ai_unavailable_placeholder(
    oral: TestOral,
    heuristic: dict[str, str],
) -> dict[str, Any]:
    """
    Réponse minimale si le LLM est indisponible : pas de paragraphe déterministe « type candidat »,
    uniquement le message d’indisponibilité demandé produit.
    """
    msg = "Analyse indisponible (données insuffisantes ou erreur IA)."
    flags = normalize_proctoring_flags(oral.cheating_flags)
    ss = flags.get("session_scores") if isinstance(flags.get("session_scores"), dict) else {}
    nivel = resolve_niveau_linguistique_final(oral.language_level_global, ss.get("language_proficiency_index"))
    tier_raw = str(heuristic.get("key") or "bon_candidat").strip()
    syn_map = {"excellent_candidat": "strong", "bon_candidat": "promising", "a_surveiller": "watch"}
    syn = syn_map.get(tier_raw, "promising")
    return {
        "synthesis_badge_key": syn,
        "badge_key": tier_raw,
        "badge_display": str(heuristic.get("label") or "Profil à analyser").strip(),
        "summary": msg,
        "strengths": [],
        "weaknesses": [],
        "recommendation": msg,
        "decision_reason": msg,
        "risk_notes": msg,
        "visual_behavior": "",
        "stress_assessment": "",
        "confidence_assessment": "",
        "suspicion_assessment": "",
        "conclusion": msg,
        "source": "ai_unavailable",
        "niveau_linguistique_final": nivel,
    }


def _ai_cache_entry_valid(cached: Any, fp: str) -> bool:
    if not isinstance(cached, dict):
        return False
    if cached.get("cache_fingerprint") != fp:
        return False
    if int(cached.get("schema_version") or 0) < AI_REPORT_SCHEMA_VERSION:
        return False
    if not str(cached.get("summary") or "").strip():
        return False
    if "strengths" not in cached or "weaknesses" not in cached:
        return False
    return True


def _cached_ai_to_response(cached: dict[str, Any]) -> dict[str, Any]:
    return {
        "synthesis_badge_key": cached.get("synthesis_badge_key", ""),
        "badge_key": cached.get("badge_key", "bon_candidat"),
        "badge_display": cached.get("badge_display", "Bon candidat"),
        "summary": cached.get("summary", ""),
        "strengths": _str_list(cached.get("strengths")),
        "weaknesses": _str_list(cached.get("weaknesses")),
        "recommendation": cached.get("recommendation", ""),
        "decision_reason": cached.get("decision_reason", ""),
        "risk_notes": cached.get("risk_notes", ""),
        "visual_behavior": cached.get("visual_behavior", ""),
        "stress_assessment": cached.get("stress_assessment", ""),
        "confidence_assessment": cached.get("confidence_assessment", ""),
        "suspicion_assessment": cached.get("suspicion_assessment", ""),
        "conclusion": cached.get("conclusion", ""),
        "source": cached.get("source", "cached"),
        "niveau_linguistique_final": cached.get("niveau_linguistique_final"),
    }


def ensure_ai_report_cached(
    db: Session,
    oral: TestOral,
    questions: list[OralTestQuestion],
    proctoring_key: str,
    force_refresh: bool,
    job_title: Optional[str] = None,
) -> dict[str, Any]:
    """Met en cache dans cheating_flags.enterprise_report_ai si besoin."""
    flags = normalize_proctoring_flags(oral.cheating_flags)
    fp = _cache_fingerprint(oral, questions)
    cached = flags.get("enterprise_report_ai")
    if not force_refresh and _ai_cache_entry_valid(cached, fp):
        merged = _apply_ai_report_coherence(_cached_ai_to_response(cached), oral, flags)
        return {
            k: v
            for k, v in merged.items()
            if k not in ("confidence_score_report", "stress_score_report")
        }

    heur = heuristic_badge(oral, questions)
    rich = _build_ai_rich_context(db, oral, questions, job_title or "")
    ai = _groq_report_json(oral, questions, proctoring_key, heur, rich)
    if ai:
        out = ai
        out = _apply_ai_report_coherence(out, oral, flags)
    else:
        out = _ai_unavailable_placeholder(oral, heur)

    store = {
        **{k: v for k, v in out.items() if k not in ("confidence_score_report", "stress_score_report")},
        "schema_version": AI_REPORT_SCHEMA_VERSION,
        "cache_fingerprint": fp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    flags["enterprise_report_ai"] = store
    oral.cheating_flags = flags
    ensure_oral_proctoring_fields(oral)
    db.add(oral)
    db.commit()
    return {
        k: v
        for k, v in out.items()
        if k not in ("confidence_score_report", "stress_score_report")
    }


def format_timeline_entries(
    flags: dict[str, Any],
    started_at: Optional[datetime],
) -> list[dict[str, Any]]:
    """Ajoute label_fr et offset_mmss pour affichage."""
    tl = flags.get("timeline") or []
    if not isinstance(tl, list):
        return []
    base: Optional[datetime] = None
    if started_at:
        base = started_at if started_at.tzinfo else started_at.replace(tzinfo=None)

    out: list[dict[str, Any]] = []
    for ev in tl[-80:]:
        if not isinstance(ev, dict):
            continue
        typ = str(ev.get("type", ""))
        ts_raw = ev.get("ts")
        mmss = "—"
        if base and ts_raw:
            try:
                from datetime import datetime as dt

                t = dt.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if t.tzinfo:
                    t = t.replace(tzinfo=None)
                b = base.replace(tzinfo=None) if base.tzinfo else base
                sec = max(0, int((t - b).total_seconds()))
                mm = sec // 60
                ss = sec % 60
                mmss = f"{mm:02d}:{ss:02d}"
            except Exception:
                mmss = str(ts_raw)[:8]
        out.append(
            {
                "time_display": mmss,
                "ts": ts_raw,
                "type": typ,
                "label_fr": EVENT_LABELS_FR.get(typ, typ),
                "detail": ev.get("detail") or ev.get("faces") or ev.get("gaze"),
            }
        )
    return out


def build_questions_payload(
    questions: list[OralTestQuestion],
    test_oral: TestOral,
) -> list[dict[str, Any]]:
    flags = normalize_proctoring_flags(test_oral.cheating_flags)
    rows = []
    for q in sorted(questions, key=lambda x: x.question_order):
        rel = float(q.relevance_score) if q.relevance_score is not None else None
        hes = float(q.hesitation_score) if q.hesitation_score is not None else None
        insight: dict[str, Any] = dict(get_answer_insight(flags, q.question_order) or {})
        if insight.get("final_answer_score") is None and (q.transcript_text or "").strip():
            dur = int(q.answer_duration_seconds or 30)
            full = analyze_transcript_only(q.question_text or "", q.transcript_text or "", dur)
            insight = insight_blob_from_analysis(full)
        fin = float(insight["final_answer_score"]) if insight.get("final_answer_score") is not None else None
        tlang = str(insight.get("transcript_language") or "").strip() or None
        tconf = (
            float(insight["transcript_confidence"])
            if insight.get("transcript_confidence") is not None
            else None
        )
        clar = float(insight["clarity_score"]) if insight.get("clarity_score") is not None else None
        langq = (
            float(insight["language_quality_score"])
            if insight.get("language_quality_score") is not None
            else None
        )
        aconf = float(insight["confidence_score"]) if insight.get("confidence_score") is not None else None
        is_ok = insight.get("is_correct")
        comment = insight.get("evaluation_comment")
        tx = (q.transcript_text or "").strip()
        coh_raw = insight.get("coherence_score")
        try:
            coh_f = float(coh_raw) if coh_raw is not None else compute_text_coherence_score(tx)
        except (TypeError, ValueError):
            coh_f = compute_text_coherence_score(tx)
        hes_f = float(hes) if hes is not None else 40.0
        rel_f = float(rel) if rel is not None else 0.0
        ql = quality_label(rel, hes, fin, transcript=tx, coherence_score=coh_f)
        comp = _composite_quality_score(rel_f, hes_f, coh_f)
        print(
            "[QUALITY DEBUG]",
            {
                "question_order": q.question_order,
                "pertinence": rel,
                "hesitation": hes,
                "coherence_score": round(coh_f, 2),
                "composite_quality_score": round(comp, 2),
                "final_quality": ql,
            },
            flush=True,
        )
        rows.append(
            {
                "question_order": q.question_order,
                "question_text": q.question_text,
                "transcript_text": q.transcript_text,
                "audio_url": q.audio_url,
                "answer_duration_seconds": q.answer_duration_seconds,
                "relevance_score": rel,
                "hesitation_score": hes,
                "coherence_score": round(coh_f, 2),
                "composite_quality_score": round(comp, 2),
                "transcript_language": tlang,
                "language_detected": tlang,
                "transcript_confidence": tconf,
                "clarity_score": clar,
                "language_quality_score": langq,
                "answer_confidence_score": aconf,
                "final_answer_score": fin,
                "is_correct": is_ok if isinstance(is_ok, bool) else None,
                "evaluation_comment": str(comment) if comment else None,
                "answer_correctness_label": answer_correctness_label(insight, rel),
                "quality_label": ql,
            }
        )
    return rows


def primary_snapshot_url(flags: dict[str, Any]) -> Optional[str]:
    snaps = flags.get("snapshots")
    if not isinstance(snaps, list) or not snaps:
        return None
    last = snaps[-1]
    if isinstance(last, dict) and last.get("url"):
        return str(last["url"])
    return None


def _resolve_snapshot_local_path_from_url(url: str) -> Optional[Path]:
    """
    Convertit un URL relatif `/uploads/oral_snapshots/<file>` vers le chemin local (si possible).
    Ne lève pas : retourne None si format inattendu.
    """
    u = (url or "").strip()
    if not u:
        return None
    prefix = "/uploads/oral_snapshots/"
    if prefix not in u:
        return None
    name = u.split(prefix, 1)[-1].split("?", 1)[0].split("#", 1)[0].strip().strip("/")
    if not name:
        return None
    root = resolve_upload_dir(get_settings().ORAL_SNAPSHOTS_DIR)
    return (root / name).resolve()


def _resolve_upload_image_local_path_from_url(url: str) -> Optional[Path]:
    """Photo identité (`oral_photos`) ou snapshot proctoring (`oral_snapshots`)."""
    u = (url or "").strip()
    if not u:
        return None
    pairs = (
        ("/uploads/oral_photos/", get_settings().ORAL_PHOTOS_DIR),
        ("/uploads/oral_snapshots/", get_settings().ORAL_SNAPSHOTS_DIR),
    )
    for prefix, dir_key in pairs:
        if prefix not in u:
            continue
        name = u.split(prefix, 1)[-1].split("?", 1)[0].split("#", 1)[0].strip().strip("/")
        if not name:
            return None
        root = resolve_upload_dir(dir_key)
        return (root / name).resolve()
    return None


def select_candidate_snapshot_url(flags: dict[str, Any]) -> Optional[str]:
    """
    Sélection “photo candidat” :
    - préfère un snapshot dont le fichier existe, avec la plus grande taille (image souvent plus nette)
    - sinon fallback : dernier URL valide
    """
    snaps = flags.get("snapshots")
    if not isinstance(snaps, list) or not snaps:
        return None

    best_url: str | None = None
    best_size = -1
    fallback_last: str | None = None

    for item in snaps:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        fallback_last = url
        p = _resolve_snapshot_local_path_from_url(url)
        try:
            if p and p.is_file():
                sz = int(p.stat().st_size)
                if sz > best_size:
                    best_size = sz
                    best_url = url
        except OSError:
            continue

    chosen = best_url or fallback_last
    if chosen:
        p2 = _resolve_snapshot_local_path_from_url(chosen)
        print("REPORT SNAPSHOT SELECTED:", str(p2 or chosen), flush=True)
    return chosen


def append_snapshot(
    db: Session,
    oral: TestOral,
    relative_url: str,
    reason: str,
) -> None:
    flags = normalize_proctoring_flags(oral.cheating_flags)
    snaps = flags.get("snapshots")
    if not isinstance(snaps, list):
        snaps = []
    snaps.append(
        {
            "url": relative_url,
            "ts": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
    )
    flags["snapshots"] = snaps[-25:]
    oral.cheating_flags = flags
    ensure_oral_proctoring_fields(oral)
    db.add(oral)
    db.commit()


def _oral_pdf_backend_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _oral_pdf_logo_white_path() -> Optional[Path]:
    p = _oral_pdf_backend_root() / "Frontend" / "public" / "digitrec-white.png"
    return p if p.is_file() else None


def _oral_pdf_logo_blue_path() -> Optional[Path]:
    p = _oral_pdf_backend_root() / "Frontend" / "public" / "digitrec-blue.png"
    return p if p.is_file() else None


def _oral_pdf_slug_part(s: str) -> str:
    raw = unicodedata.normalize("NFKD", (s or "").strip())
    raw = "".join(c for c in raw if not unicodedata.combining(c))
    raw = raw.lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw


def oral_report_download_filename(candidature_id: str, report: dict[str, Any]) -> str:
    """Fichier téléchargeable : rapport_oral_<prenom>_<nom>.pdf (slug ASCII)."""
    p = _oral_pdf_slug_part(str(report.get("candidate_prenom") or ""))
    n = _oral_pdf_slug_part(str(report.get("candidate_nom") or ""))
    slug = "_".join(x for x in (p, n) if x)
    if slug:
        return f"rapport_oral_{slug}.pdf"
    cid = str(report.get("candidature_id") or candidature_id or "").replace("-", "_")
    return f"rapport_oral_{cid}.pdf" if cid else "rapport_oral.pdf"


def _oral_pdf_initials(candidature_id: str, display_name: Optional[str] = None) -> str:
    dn = (display_name or "").strip()
    if dn:
        parts = [p for p in dn.split() if p]
        if len(parts) >= 2 and parts[0] and parts[-1]:
            return (parts[0][0] + parts[-1][0]).upper()
        if parts:
            w = parts[0]
            if len(w) >= 2:
                return w[:2].upper()
            return (w[0] + w[0]).upper()
    raw = "".join(c for c in candidature_id if c.isalnum())
    if len(raw) >= 2:
        return raw[:2].upper()
    return "C"


def _oral_pdf_esc_xml(s: Any) -> str:
    from html import escape as esc

    return esc(str(s) if s is not None else "")


def _oral_pdf_tone_high_good(val: Optional[float], hi: float = 72, mid: float = 48) -> tuple[str, str]:
    """(libellé interprétation, couleur hex). Plus haut = mieux."""
    if val is None:
        return ("Non estimé", "#6B7280")
    v = float(val)
    if v >= hi:
        return ("Bon", "#16A34A")
    if v >= mid:
        return ("Moyen", "#F59E0B")
    return ("Faible", "#DC2626")


def _oral_pdf_tone_stress(val: Optional[float]) -> tuple[str, str]:
    if val is None:
        return ("Non estimé", "#6B7280")
    v = float(val)
    if v < 38:
        return ("Faible", "#16A34A")
    if v < 62:
        return ("Modéré", "#F59E0B")
    return ("Élevé", "#DC2626")


def _oral_pdf_tone_count_bad(n: int, low: int, high: int) -> tuple[str, str]:
    """Plus haut = plus défavorable."""
    if n <= low:
        return ("Faible", "#16A34A")
    if n <= high:
        return ("Modéré", "#F59E0B")
    return ("Élevé", "#DC2626")


def _oral_pdf_badge_colors(badge_key: Optional[str]) -> tuple[str, str]:
    k = (badge_key or "").strip().lower()
    if k == "excellent_candidat":
        return ("#16A34A", "#FFFFFF")
    if k == "bon_candidat":
        return ("#1D4ED8", "#FFFFFF")
    if k == "a_surveiller":
        return ("#DC2626", "#FFFFFF")
    return ("#F59E0B", "#111827")


def _oral_pdf_quality_style(label: str) -> tuple[str, str]:
    t = (label or "").strip().lower()
    if t == "bonne":
        return ("#DCFCE7", "#166534")
    if t == "moyenne":
        return ("#FEF3C7", "#B45309")
    return ("#FEE2E2", "#991B1B")


def _oral_pdf_suspicion_label(level: str) -> str:
    u = (level or "").strip().upper()
    if u == "LOW":
        return "Faible"
    if u == "MEDIUM":
        return "Modéré"
    if u == "HIGH":
        return "Élevé"
    return level or "—"


def build_pdf_bytes(
    offre_titre: Optional[str],
    candidature_id: str,
    report: dict[str, Any],
) -> bytes:
    """Rapport PDF entretien oral (mise en page SaaS RH, ReportLab)."""
    try:
        from html import escape as esc

        from reportlab.lib import colors
        from reportlab.lib.colors import HexColor
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            BaseDocTemplate,
            Frame,
            Image,
            KeepTogether,
            PageTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )

        generated_at = datetime.now(timezone.utc)
        to = report.get("test_oral") or {}
        if not isinstance(to, dict):
            to = {}
        br = report.get("badge") or {}
        if not isinstance(br, dict):
            br = {}
        pi = report.get("proctoring_insights") or {}
        if not isinstance(pi, dict):
            pi = {}
        beh = report.get("behavioral_analysis") or {}
        if not isinstance(beh, dict):
            beh = {}
        ai_full = report.get("ai_report") or {}
        if not isinstance(ai_full, dict):
            ai_full = {}

        blue = HexColor("#1D4ED8")
        green_hex = "#16A34A"
        orange_hex = "#EA580C"
        red_hex = "#DC2626"
        gray_bg = HexColor("#F3F6FA")
        gray_border = HexColor("#E5E7EB")
        text_dark = HexColor("#111827")
        text_muted = HexColor("#6B7280")

        def footer_canvas(canvas: Any, doc_: Any) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(text_muted)
            y = 0.85 * cm
            canvas.drawString(
                doc_.leftMargin,
                y,
                f"Généré par DigitRec — {generated_at.strftime('%d/%m/%Y %H:%M')} UTC",
            )
            num = canvas.getPageNumber()
            canvas.drawRightString(
                doc_.pagesize[0] - doc_.rightMargin,
                y,
                f"Page {num}",
            )
            canvas.restoreState()

        buf = io.BytesIO()
        lm, rm, tm, bm = 1.8 * cm, 1.8 * cm, 1.4 * cm, 2.3 * cm
        doc = BaseDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=lm,
            rightMargin=rm,
            topMargin=tm,
            bottomMargin=bm,
        )
        pw, ph = A4
        frame = Frame(
            lm,
            bm,
            pw - lm - rm,
            ph - bm - tm,
            id="oral_frame",
            leftPadding=0,
            bottomPadding=0,
            rightPadding=0,
            topPadding=0,
        )
        doc.addPageTemplates(
            [
                PageTemplate(
                    id="oral_main",
                    frames=[frame],
                    onPage=footer_canvas,
                    pagesize=A4,
                )
            ]
        )
        full_w = pw - lm - rm
        styles = getSampleStyleSheet()

        title_main = ParagraphStyle(
            name="TitleMain",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=blue,
            spaceAfter=6,
        )
        subtitle_main = ParagraphStyle(
            name="SubtitleMain",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=text_dark,
        )
        meta_main = ParagraphStyle(
            name="MetaMain",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=text_muted,
            spaceBefore=2,
        )
        section_title = ParagraphStyle(
            name="SectionTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=blue,
            spaceBefore=16,
            spaceAfter=10,
        )
        card_title = ParagraphStyle(
            name="CardTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=text_muted,
        )
        card_value = ParagraphStyle(
            name="CardValue",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=text_dark,
        )
        card_hint = ParagraphStyle(
            name="CardHint",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=text_muted,
        )
        small = ParagraphStyle(
            name="SmallPdf",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=text_dark,
        )
        small_muted = ParagraphStyle(
            name="SmallMuted",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=text_muted,
        )
        badge_text = ParagraphStyle(
            name="BadgePdf",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
        )
        body = ParagraphStyle(
            name="BodyPdf",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=text_dark,
        )
        body_bold = ParagraphStyle(
            name="BodyBoldPdf",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=text_dark,
        )

        story: list[Any] = []

        ai_summary = str(report.get("ai_summary") or "").strip()
        strengths_pdf = _str_list(ai_full.get("strengths"))
        weaknesses_pdf = _str_list(ai_full.get("weaknesses"))
        rec_pdf = str(ai_full.get("recommendation") or "").strip()
        risk_pdf = str(ai_full.get("risk_notes") or "").strip()
        decision_pdf = str(ai_full.get("decision_reason") or "").strip()
        conclusion = str(ai_full.get("conclusion") or "").strip()

        cand_display_raw = str(report.get("candidate_display_name") or "").strip()

        section_title_first = ParagraphStyle(
            name=f"SectionTitleFirst{uuid.uuid4().hex[:6]}",
            parent=section_title,
            spaceBefore=6,
        )

        # --- Photo / avatar (3,5 cm) ---
        photo_size = 3.5 * cm
        cand_url = (
            str(report.get("candidate_photo_url") or "").strip()
            or str(report.get("candidate_image_url") or "").strip()
            or str(report.get("primary_snapshot_url") or "").strip()
        )
        photo_flow: Any = None
        if cand_url:
            p_img = _resolve_upload_image_local_path_from_url(cand_url)
            if p_img and p_img.is_file():
                try:
                    photo_flow = Image(str(p_img), width=photo_size, height=photo_size)
                except Exception as exc:
                    logger.warning("build_pdf_bytes: image candidat ignorée: %s", exc)
        if photo_flow is None:
            initials = _oral_pdf_initials(candidature_id, cand_display_raw)
            avatar_style = ParagraphStyle(
                name=f"AvatarInitials{uuid.uuid4().hex[:6]}",
                parent=styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=22,
                alignment=TA_CENTER,
                textColor=text_muted,
            )
            photo_flow = Table(
                [[Paragraph(initials, avatar_style)]],
                colWidths=[photo_size],
                rowHeights=[photo_size],
            )
            photo_flow.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#E5E7EB")),
                        ("BOX", (0, 0), (-1, -1), 0.75, gray_border),
                    ]
                )
            )

        badge_key = str(br.get("badge_key") or "")
        badge_display = str(br.get("badge_display") or "—")
        badge_bg, badge_fg = _oral_pdf_badge_colors(badge_key)
        badge_para = Paragraph(
            f'<font color="{badge_fg}">{esc(badge_display)}</font>',
            ParagraphStyle(
                name=f"BadgeInner{uuid.uuid4().hex[:6]}",
                parent=badge_text,
                textColor=HexColor(badge_fg),
            ),
        )
        badge_cell = Table([[badge_para]], colWidths=[4.2 * cm])
        badge_cell.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), HexColor(badge_bg)),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )

        poste = _oral_pdf_esc_xml(offre_titre or (report.get("offre_titre") or "—"))
        report_date = generated_at.strftime("%d/%m/%Y")
        cand_name = _oral_pdf_esc_xml(cand_display_raw or "Candidat")

        logo_flow: Any = Spacer(2.7 * cm, 0.4 * cm)
        lp_blue = _oral_pdf_logo_blue_path()
        if lp_blue:
            try:
                logo_flow = Image(str(lp_blue), width=2.6 * cm, height=0.75 * cm)
            except Exception:
                pass

        title_stack = [
            Paragraph("RAPPORT D'ENTRETIEN ORAL", title_main),
            Paragraph(
                f"<b>{cand_name}</b><br/><font color='#6B7280'>Poste visé : {poste}</font>",
                subtitle_main,
            ),
            Paragraph(f"Date du rapport : {report_date}", meta_main),
            Spacer(1, 0.14 * cm),
            badge_cell,
        ]
        title_cell = Table([[x] for x in title_stack], colWidths=[full_w - photo_size - 2.85 * cm])
        title_cell.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

        logo_cell = Table([[logo_flow]], colWidths=[2.75 * cm])
        logo_cell.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

        photo_cell = Table([[photo_flow]], colWidths=[photo_size])
        photo_cell.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )

        header_inner = Table(
            [[logo_cell, title_cell, photo_cell]],
            colWidths=[2.75 * cm, full_w - photo_size - 2.85 * cm, photo_size],
        )
        header_inner.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

        header_row = Table([[header_inner]], colWidths=[full_w])
        header_row.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("LINEBELOW", (0, 0), (-1, -1), 2.5, blue),
                ]
            )
        )
        story.append(header_row)
        story.append(Spacer(1, 0.5 * cm))

        # --- Résumé (cartes) ---
        oral_v = to.get("score_oral_global")
        oral_f = float(oral_v) if oral_v is not None else None
        conf_v = to.get("confidence_score")
        conf_f = float(conf_v) if conf_v is not None else None
        stress_v = to.get("stress_score")
        stress_f = float(stress_v) if stress_v is not None else None
        lang_disp = str(to.get("language_display") or to.get("language_level_global") or "—")

        o_lab, o_hex = _oral_pdf_tone_high_good(oral_f)
        c_lab, c_hex = _oral_pdf_tone_high_good(conf_f)
        s_lab, s_hex = _oral_pdf_tone_stress(stress_f)

        gap_w = 0.12 * cm
        card_w = (full_w - 3 * gap_w) / 4

        def metric_card(
            title: str, value_str: str, interp: str, color_hex: str, *, big_value: bool = False
        ) -> Table:
            safe_hex = color_hex.replace("#", "x")
            base = ParagraphStyle(
                name=f"CardVal{safe_hex}{uuid.uuid4().hex[:4]}",
                parent=card_value,
                textColor=HexColor(color_hex),
            )
            v_style = ParagraphStyle(
                name=f"CardValSz{safe_hex}{uuid.uuid4().hex[:4]}",
                parent=base,
                fontSize=26 if big_value else 18,
                leading=30 if big_value else 22,
            )
            inner = Table(
                [
                    [Paragraph(title, card_title)],
                    [Paragraph(value_str, v_style)],
                    [Paragraph(interp, card_hint)],
                ],
                colWidths=[card_w],
            )
            inner.setStyle(
                TableStyle(
                    [
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            outer = Table([[inner]], colWidths=[card_w])
            outer.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), gray_bg),
                        ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            return outer

        m1 = metric_card(
            "Score oral",
            "—" if oral_f is None else f"{oral_f:.0f}",
            o_lab,
            o_hex,
            big_value=True,
        )
        m2 = metric_card("Confiance", "—" if conf_f is None else f"{conf_f:.0f}", c_lab, c_hex)
        m3 = metric_card("Stress", "—" if stress_f is None else f"{stress_f:.0f}", s_lab, s_hex)
        lang_val_style = ParagraphStyle(
            name=f"LangVal{uuid.uuid4().hex[:6]}",
            parent=card_value,
            fontSize=12,
            leading=15,
            textColor=text_dark,
        )
        m4_inner = Table(
            [
                [Paragraph("Niveau linguistique", card_title)],
                [
                    Paragraph(
                        _oral_pdf_esc_xml(lang_disp[:80]),
                        lang_val_style,
                    )
                ],
                [Paragraph("Estimation auto", card_hint)],
            ],
            colWidths=[card_w],
        )
        m4_inner.setStyle(
            TableStyle(
                [
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        m4 = Table([[m4_inner]], colWidths=[card_w])
        m4.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), gray_bg),
                    ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                ]
            )
        )
        cards_row = Table(
            [
                [
                    m1,
                    Spacer(gap_w, 0.1 * cm),
                    m2,
                    Spacer(gap_w, 0.1 * cm),
                    m3,
                    Spacer(gap_w, 0.1 * cm),
                    m4,
                ]
            ],
            colWidths=[card_w, gap_w, card_w, gap_w, card_w, gap_w, card_w],
            hAlign="LEFT",
        )
        cards_row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(Paragraph("Résumé", section_title_first))
        story.append(cards_row)
        story.append(Spacer(1, 0.45 * cm))

        # --- Synthèse RH (un seul bloc, sans titre dupliqué) ---
        story.append(Paragraph("Synthèse RH", section_title))
        if ai_summary:
            syn_inner: list[Any] = [Paragraph(_oral_pdf_esc_xml(ai_summary), body)]
        else:
            syn_inner = [Paragraph("<i>Aucune synthèse IA disponible pour cette session.</i>", small_muted)]
        syn_block = Table([[syn_inner]], colWidths=[full_w])
        syn_block.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), gray_bg),
                    ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        story.append(syn_block)
        story.append(Spacer(1, 0.4 * cm))

        # --- Points forts / à améliorer (deux colonnes) ---
        story.append(Paragraph("Profil candidat", section_title))
        cw_half = (full_w - 0.45 * cm) / 2

        def _build_pf_column(header_html: str, items: list[str], bullet_color: str) -> Table:
            rows: list[list[Any]] = [[Paragraph(header_html, body)]]
            if items:
                for s in items:
                    rows.append(
                        [
                            Paragraph(
                                f'<font color="{bullet_color}">•</font> {_oral_pdf_esc_xml(s)}',
                                body,
                            )
                        ]
                    )
            else:
                rows.append([Paragraph("<i>Non renseigné</i>", small_muted)])
            tbl = Table(rows, colWidths=[cw_half])
            tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
                        ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            return tbl

        col_sf = _build_pf_column(
            f'<b><font color="{green_hex}">✔ Points forts</font></b>',
            strengths_pdf,
            green_hex,
        )
        col_wk = _build_pf_column(
            f'<b><font color="{orange_hex}">⚠ Points à améliorer</font></b>',
            weaknesses_pdf,
            orange_hex,
        )
        dual_pf = Table([[col_sf, col_wk]], colWidths=[cw_half, cw_half])
        dual_pf.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (1, 0), (1, 0), 8),
                ]
            )
        )
        story.append(dual_pf)
        story.append(Spacer(1, 0.45 * cm))

        # --- Proctoring (tableau + statuts) ---
        tabs = int(to.get("tab_switch_count") or 0)
        fs = int(to.get("fullscreen_exit_count") or 0)
        pres = bool(to.get("presence_anomaly_detected"))
        phone = bool(to.get("phone_detected"))
        other = bool(to.get("other_person_detected"))
        dom = str(pi.get("dominant_direction") or "—")
        move = str(pi.get("movement_level") or "—")
        susp = str(pi.get("suspicion_level") or "—")
        pres_pr = str(pi.get("presence_professional") or "").strip()
        susp_pr = str(pi.get("suspicion_professional") or "").strip()
        s_score = pi.get("suspicion_score")

        susp_disp = _oral_pdf_suspicion_label(susp)
        susp_u = susp.strip().upper()

        def proc_status_mark(level: str) -> Paragraph:
            if level == "ok":
                return Paragraph(f'<font color="{green_hex}">✔ Normal</font>', small)
            if level == "warn":
                return Paragraph('<font color="#F59E0B">⚠ À surveiller</font>', small)
            return Paragraph(f'<font color="{red_hex}">❌ Anomalie</font>', small)

        def lvl_count(n: int, ok_max: int, warn_max: int) -> str:
            if n <= ok_max:
                return "ok"
            if n <= warn_max:
                return "warn"
            return "bad"

        def lvl_susp(u: str) -> str:
            uu = u.strip().upper()
            if uu == "HIGH":
                return "bad"
            if uu == "MEDIUM":
                return "warn"
            return "ok"

        if pres_pr:
            pres_raw = (pres_pr[:220] + "…") if len(pres_pr) > 220 else pres_pr
        else:
            pres_raw = "Anomalie signalée" if pres else "Stable"
        pres_detail = Paragraph(_oral_pdf_esc_xml(pres_raw), body)

        susp_raw = (susp_pr[:220] + "…") if len(susp_pr) > 220 else susp_pr if susp_pr else susp_disp
        if s_score is not None:
            try:
                susp_raw = f"{susp_raw} ({float(s_score):.0f}/100)"
            except (TypeError, ValueError):
                pass
        susp_para = Paragraph(_oral_pdf_esc_xml(susp_raw), body)

        proc_data = [
            [
                Paragraph("<b>Indicateur</b>", small),
                Paragraph("<b>Synthèse</b>", small),
                Paragraph("<b>Statut</b>", small),
            ],
            [
                Paragraph("Changements d’onglet", body),
                Paragraph(str(tabs), body),
                proc_status_mark(lvl_count(tabs, 2, 5)),
            ],
            [
                Paragraph("Sorties plein écran", body),
                Paragraph(str(fs), body),
                proc_status_mark(lvl_count(fs, 1, 3)),
            ],
            [
                Paragraph("Présence & visage", body),
                pres_detail,
                proc_status_mark("bad" if pres else "ok"),
            ],
            [
                Paragraph("Signal téléphone", body),
                Paragraph("Oui" if phone else "Non", body),
                proc_status_mark("bad" if phone else "ok"),
            ],
            [
                Paragraph("Autre personne (cadre)", body),
                Paragraph("Oui" if other else "Non", body),
                proc_status_mark("bad" if other else "ok"),
            ],
            [
                Paragraph("Regard dominant", body),
                Paragraph(_oral_pdf_esc_xml(dom), body),
                proc_status_mark("ok"),
            ],
            [
                Paragraph("Niveau d’activité (mouvement)", body),
                Paragraph(_oral_pdf_esc_xml(move), body),
                proc_status_mark("ok"),
            ],
            [
                Paragraph("Niveau de suspicion", body),
                susp_para,
                proc_status_mark(lvl_susp(susp_u)),
            ],
        ]
        c_ind, c_syn, c_st = full_w * 0.28, full_w * 0.52, full_w * 0.2
        proc_tbl = Table(proc_data, colWidths=[c_ind, c_syn, c_st])
        proc_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EEF2FF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), text_dark),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, gray_border),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 1), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#FAFAFA")]),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ]
            )
        )
        story.append(Paragraph("Proctoring", section_title))
        story.append(proc_tbl)
        story.append(Spacer(1, 0.4 * cm))

        # --- Analyse comportementale ---
        beh_labels = [
            ("Regard", str(beh.get("visual") or "").strip()),
            ("Stress perçu", str(beh.get("stress") or "").strip()),
            ("Confiance perçue", str(beh.get("confidence") or "").strip()),
            ("Suspicion / intégrité de session", str(beh.get("suspicion") or "").strip()),
        ]
        beh_lines: list[Any] = []
        for label, txt in beh_labels:
            if not txt:
                continue
            beh_lines.append(
                Paragraph(f"• <b>{esc(label)} :</b> {_oral_pdf_esc_xml(txt)}", body)
            )
        if beh_lines:
            story.append(Paragraph("Analyse comportementale", section_title))
            beh_tbl = Table([[ln] for ln in beh_lines], colWidths=[full_w])
            beh_tbl.setStyle(
                TableStyle(
                    [
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(beh_tbl)
            story.append(Spacer(1, 0.4 * cm))

        # --- Complément d’analyse IA ---
        deep_ai: list[Any] = []
        if rec_pdf:
            deep_ai.append(Paragraph(f"• <b>Recommandation RH :</b> {_oral_pdf_esc_xml(rec_pdf)}", body))
        if risk_pdf:
            deep_ai.append(Paragraph(f"• <b>Risques / vigilance :</b> {_oral_pdf_esc_xml(risk_pdf)}", body))
        if decision_pdf:
            deep_ai.append(Paragraph(f"• <b>Motif (données) :</b> {_oral_pdf_esc_xml(decision_pdf)}", small))
        if conclusion:
            deep_ai.append(Paragraph(f"• <b>Conclusion :</b> {_oral_pdf_esc_xml(conclusion)}", body_bold))
        if deep_ai:
            story.append(Paragraph("Complément d’analyse IA", section_title))
            ai_box = Table([[deep_ai]], colWidths=[full_w])
            ai_box.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FAFAFA")),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(ai_box)
            story.append(Spacer(1, 0.4 * cm))

        # --- Questions & réponses ---
        story.append(Paragraph("Questions & réponses", section_title))
        for q in report.get("questions") or []:
            qo = q.get("question_order")
            ql = str(q.get("quality_label") or "")
            rel = q.get("relevance_score")
            hes = q.get("hesitation_score")
            rel_s = f"{float(rel):.0f}" if rel is not None else "—"
            hes_s = f"{float(hes):.0f}" if hes is not None else "—"
            bg, fg = _oral_pdf_quality_style(ql)
            badge_q = Paragraph(
                esc(ql or "—"),
                ParagraphStyle(
                    name=f"QBadge{uuid.uuid4().hex[:8]}",
                    parent=small,
                    textColor=HexColor(fg),
                    fontName="Helvetica-Bold",
                    alignment=TA_CENTER,
                ),
            )
            badge_col_w = 2.35 * cm
            badge_wrap = Table([[badge_q]], colWidths=[badge_col_w])
            badge_wrap.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg)),
                        ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            meta_line = Paragraph(
                f"<b>Pertinence :</b> {esc(rel_s)} &nbsp;&nbsp; <b>Hésitation :</b> {esc(hes_s)}",
                small_muted,
            )
            top_bar = Table(
                [[badge_wrap, meta_line]],
                colWidths=[badge_col_w, full_w - badge_col_w],
            )
            top_bar.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (1, 0), (1, 0), 8),
                    ]
                )
            )
            q_label = Paragraph(f"<font color='#6B7280'>Question {qo}</font>", small_muted)
            qt = _oral_pdf_esc_xml((q.get("question_text") or "")[:2000])
            tr = _oral_pdf_esc_xml((q.get("transcript_text") or "")[:4000])
            answer_box = Table(
                [[Paragraph(f"<b>Réponse</b><br/>{tr}", body)]],
                colWidths=[full_w],
            )
            answer_box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F9FAFB")),
                        ("BOX", (0, 0), (-1, -1), 0.5, gray_border),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            q_card = Table(
                [
                    [q_label],
                    [Spacer(1, 0.08 * cm)],
                    [top_bar],
                    [Spacer(1, 0.14 * cm)],
                    [Paragraph(qt, body)],
                    [Spacer(1, 0.12 * cm)],
                    [answer_box],
                ],
                colWidths=[full_w],
            )
            q_card.setStyle(
                TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.75, gray_border),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(KeepTogether([q_card, Spacer(1, 0.35 * cm)]))

        doc.build(story)
        return buf.getvalue()
    except Exception as exc:
        logger.exception("build_pdf_bytes: %s", exc)
        raise


def build_enterprise_report_payload(
    db: Session,
    test_oral: TestOral,
    questions: list[OralTestQuestion],
    offre_titre: Optional[str],
    candidature_id: UUID,
    force_refresh_ai: bool,
) -> dict[str, Any]:
    """Payload unique pour GET JSON et PDF."""
    flags = normalize_proctoring_flags(test_oral.cheating_flags)
    proc_key = proctoring_summary_key(test_oral, flags)
    session_scores = flags.get("session_scores")
    if not isinstance(session_scores, dict):
        session_scores = {}
    conf_disp, stress_disp = normalize_confidence_stress(
        test_oral.confidence_score,
        test_oral.stress_score,
    )
    nivel_final = resolve_niveau_linguistique_final(
        test_oral.language_level_global,
        session_scores.get("language_proficiency_index"),
    )
    ai = ensure_ai_report_cached(
        db, test_oral, questions, proc_key, force_refresh_ai, job_title=offre_titre or ""
    )
    questions_out = build_questions_payload(questions, test_oral)
    photo_rel = (test_oral.candidate_photo_url or "").strip() or None

    counters = flags.get("counters")
    if not isinstance(counters, dict):
        counters = {}
    estimates = flags.get("estimates")
    if not isinstance(estimates, dict):
        estimates = {}

    head_pose = estimates.get("head_pose") if isinstance(estimates.get("head_pose"), dict) else {}
    head_yaw = head_pose.get("head_yaw")
    head_pitch = head_pose.get("head_pitch")
    suspicious_head = (
        int(counters.get("suspicious_head_movement_heartbeat_count") or 0) >= 1
        or int(getattr(test_oral, "suspicious_movements_count", 0) or 0) > 0
        or head_pose.get("suspicious_head_movement") is True
    )

    phone_effective = False
    _pm = estimates.get("phone_metrics")
    phone_metrics = _pm if isinstance(_pm, dict) else {}
    _pps = phone_metrics.get("phone_posture_score")
    _pmd = phone_metrics.get("phone_detected")
    if test_oral.phone_detected is True:
        phone_effective = True
    elif int(counters.get("phone_detected_events") or 0) > 0:
        phone_effective = True
    elif _pmd is True:
        phone_effective = True
    elif isinstance(_pps, (int, float)) and not isinstance(_pps, bool) and float(_pps) >= 0.25:
        phone_effective = True

    presence_effective = False
    _prm = estimates.get("presence_metrics")
    presence_metrics = _prm if isinstance(_prm, dict) else {}
    if test_oral.presence_anomaly_detected is True:
        presence_effective = True
    elif int(counters.get("presence_anomaly_events") or 0) > 0:
        presence_effective = True
    elif presence_metrics.get("presence_anomaly_detected") is True:
        presence_effective = True
    elif int(counters.get("face_not_visible_count") or 0) >= 2:
        presence_effective = True
    elif int(counters.get("multiple_faces_count") or 0) >= 1:
        presence_effective = True

    conf_for_label = conf_disp if conf_disp is not None else test_oral.confidence_score
    stress_for_label = stress_disp if stress_disp is not None else test_oral.stress_score
    test_payload = {
        "id": str(test_oral.id),
        "score_oral_global": test_oral.score_oral_global,
        "confidence_score": conf_for_label,
        "stress_score": stress_for_label,
        "confidence_score_db": test_oral.confidence_score,
        "stress_score_db": test_oral.stress_score,
        "communication_score": session_scores.get("communication_avg"),
        "technical_score": session_scores.get("technical_avg"),
        "cheating_score": estimates.get("cheating_score"),
        "final_decision": session_scores.get("final_decision"),
        "confidence_label": confidence_label(
            float(conf_for_label) if conf_for_label is not None else None
        ),
        "stress_label": stress_label(
            float(stress_for_label) if stress_for_label is not None else None
        ),
        "language_level_global": test_oral.language_level_global,
        "niveau_linguistique_final": nivel_final,
        "language_display": f"Niveau CECRL {nivel_final}",
        "language_proficiency_index": session_scores.get("language_proficiency_index"),
        "soft_skills_summary": test_oral.soft_skills_summary,
        "eye_contact_score_global": test_oral.eye_contact_score_global,
        "tab_switch_count": test_oral.tab_switch_count,
        "fullscreen_exit_count": test_oral.fullscreen_exit_count,
        "suspicious_movements_count": test_oral.suspicious_movements_count,
        "presence_anomaly_detected": presence_effective,
        "phone_detected": phone_effective,
        "other_person_detected": test_oral.other_person_detected,
        "cheating_flags_global": get_proctoring_summary_text(test_oral),
        "proctoring_counters": dict(counters),
        "cheating_risk_level": estimates.get("cheating_risk_level"),
        "proctoring_estimates": dict(estimates),
        "started_at": test_oral.started_at.isoformat() if test_oral.started_at else None,
        "finished_at": test_oral.finished_at.isoformat() if test_oral.finished_at else None,
        "duration_seconds": test_oral.duration_seconds,
        "status": test_oral.status,
        "proctoring_summary_key": proc_key,
        "proctoring_summary_label": proctoring_summary_label(proc_key),
        "candidate_access_token_set": bool((test_oral.candidate_access_token or "").strip()),
        "candidate_photo_url": photo_rel,
    }

    # Interprétation « humaine » (déterministe, rapide) — sans nouvel appel IA.
    gaze = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    g_samples = int(gaze.get("samples") or 0)
    off_ratio = float(gaze.get("off_ratio") or 0.0)
    down_ratio = float(gaze.get("down_ratio") or 0.0)
    left_ratio = float(gaze.get("left_ratio") or 0.0)
    right_ratio = float(gaze.get("right_ratio") or 0.0)
    center_ratio = float(gaze.get("center_ratio") or 0.0)
    rapid = int(counters.get("rapid_motion_heartbeat_count") or 0)
    looking_down = int(counters.get("looking_down_count") or 0)
    max_faces = int(counters.get("max_faces_count") or 0)
    phone_peak = float(counters.get("phone_confidence_peak") or 0.0)
    suspicion_level = str(estimates.get("cheating_risk_level") or "").strip() or "—"
    if suspicion_level not in ("LOW", "MEDIUM", "HIGH"):
        if test_oral.phone_detected or test_oral.other_person_detected:
            suspicion_level = "HIGH"
        elif off_ratio >= 0.45 or rapid >= 8 or (test_oral.tab_switch_count or 0) >= 6:
            suspicion_level = "MEDIUM"
        else:
            suspicion_level = "LOW"

    gz = estimates.get("gaze_quality")
    mv = estimates.get("movement_analysis")
    pres = estimates.get("presence_analysis")
    susp_a = estimates.get("suspicion_assessment")

    if isinstance(gz, dict) and gz.get("label"):
        gaze_stability = str(gz["label"])
        dominant_direction = str(gz.get("dominant_direction") or "—")
        gaze_explanation = str(gz.get("explanation") or "").strip()
        gaze_score = gz.get("score")
        gaze_professional = (
            f"{gaze_stability.capitalize()} — {gaze_explanation}"
            if gaze_explanation
            else gaze_stability
        )
    else:
        gaze_stability = str(estimates.get("gaze_stability_label") or "—")
        dominant_direction = (
            "centre"
            if center_ratio >= max(off_ratio, down_ratio, left_ratio, right_ratio)
            else "hors cadre"
            if off_ratio >= max(center_ratio, down_ratio, left_ratio, right_ratio)
            else "bas"
            if down_ratio >= max(center_ratio, off_ratio, left_ratio, right_ratio)
            else "gauche"
            if left_ratio >= right_ratio
            else "droite"
        )
        gaze_explanation = ""
        gaze_score = None
        gaze_professional = (
            f"{gaze_stability} — agrégat historique (détail regard non disponible)."
            if gaze_stability and gaze_stability != "—"
            else "Données de regard limitées sur cette session."
        )

    if isinstance(mv, dict) and mv.get("label"):
        movement_level = str(mv["label"])
        movement_explanation = str(mv.get("explanation") or "").strip()
        movement_score = mv.get("score")
        movement_professional = (
            f"{movement_level.capitalize()} — {movement_explanation}"
            if movement_explanation
            else movement_level
        )
    else:
        movement_level = "élevé" if rapid >= 10 else "modéré" if rapid >= 5 else "faible"
        movement_explanation = ""
        movement_score = None
        movement_professional = (
            f"{movement_level.capitalize()} — estimation à partir des heartbeats (rapport historique)."
        )

    if isinstance(pres, dict) and pres.get("label"):
        presence_stability = str(pres["label"])
        presence_explanation = str(pres.get("explanation") or "").strip()
        presence_score = pres.get("score")
        presence_professional = (
            f"{presence_stability.capitalize()} — {presence_explanation}"
            if presence_explanation
            else presence_stability
        )
    else:
        presence_stability = "instable" if presence_effective else "stable"
        presence_explanation = ""
        presence_score = None
        presence_professional = (
            f"{presence_stability.capitalize()} — indicateur dérivé des anomalies de présence enregistrées."
        )

    if isinstance(susp_a, dict) and susp_a.get("level"):
        suspicion_level = str(susp_a.get("level") or suspicion_level)
        suspicion_numeric = susp_a.get("score")
        suspicion_explanation = str(susp_a.get("explanation") or "").strip()
        sigs = susp_a.get("signals")
    else:
        suspicion_numeric = estimates.get("suspicion_score")
        suspicion_explanation = ""
        sigs = None

    # --- Planchers finaux côté rapport (affichage cohérent avec signaux) ---
    try:
        susp_val = float(suspicion_numeric) if suspicion_numeric is not None else 0.0
    except Exception:
        susp_val = 0.0
    head_cnt = int(counters.get("suspicious_head_movement_heartbeat_count") or 0)
    sql_head_cnt = int(getattr(test_oral, "suspicious_movements_count", 0) or 0)
    head_repeated = head_cnt >= 2 or sql_head_cnt >= 2
    if phone_effective or presence_effective:
        susp_val = max(susp_val, 35.0)
    if suspicious_head:
        if head_repeated:
            susp_val = max(susp_val, 35.0)
        else:
            susp_val = max(susp_val, 25.0)
    suspicion_numeric = round(susp_val, 2)
    _sl = str(suspicion_level).strip().upper()
    if (phone_effective or presence_effective) and _sl == "LOW":
        suspicion_level = "MEDIUM"
    elif suspicious_head and head_repeated and _sl == "LOW":
        suspicion_level = "MEDIUM"

    if isinstance(susp_a, dict) and susp_a.get("level"):
        suspicion_professional = (
            f"{suspicion_level} ({suspicion_numeric}/100) — {suspicion_explanation}"
            if suspicion_numeric is not None and suspicion_explanation
            else (
                f"{suspicion_level} ({suspicion_numeric}/100)"
                if suspicion_numeric is not None
                else suspicion_explanation or f"Niveau {suspicion_level} (agrégat proctoring)."
            )
        )
    else:
        suspicion_professional = (
            f"{suspicion_level} ({suspicion_numeric}/100) — interprétation à partir des compteurs disponibles."
            if suspicion_numeric is not None
            else f"{suspicion_level} — interprétation à partir des compteurs disponibles."
        )

    proctoring_insights = {
        "gaze_stability": gaze_stability,
        "dominant_direction": dominant_direction,
        "gaze_professional": gaze_professional,
        "gaze_explanation": gaze_explanation,
        "gaze_score": gaze_score,
        "movement_level": movement_level,
        "movement_professional": movement_professional,
        "movement_explanation": movement_explanation,
        "movement_score": movement_score,
        "head_movement": "suspect" if suspicious_head else "normal",
        "head_yaw": head_yaw,
        "head_pitch": head_pitch,
        "presence_stability": presence_stability,
        "presence_professional": presence_professional,
        "presence_explanation": presence_explanation,
        "presence_score": presence_score,
        "suspicion_level": suspicion_level,
        "suspicion_professional": suspicion_professional,
        "suspicion_score": suspicion_numeric,
        "suspicion_signals": sigs,
        "signals": {
            "phone_detected": bool(phone_effective),
            "phone_confidence_peak": round(phone_peak, 3),
            "other_person_detected": bool(test_oral.other_person_detected),
            "max_faces_count": max_faces,
            "presence_anomaly_detected": bool(presence_effective),
            "gaze_off_ratio": round(off_ratio, 4),
            "gaze_down_ratio": round(down_ratio, 4),
            "gaze_samples": g_samples,
            "looking_down_count": looking_down,
            "rapid_motion_heartbeat_count": rapid,
            "suspicious_head_movement": suspicious_head,
            "head_yaw": head_yaw,
            "head_pitch": head_pitch,
        },
    }

    print(
        "BACKEND FINAL PROCTORING REPORT VALUES",
        {
            "oral_id": str(test_oral.id),
            "phone_detected_db": bool(test_oral.phone_detected),
            "phone_detected_effective": bool(phone_effective),
            "suspicious_movements_count": int(test_oral.suspicious_movements_count or 0),
            "suspicious_head_movement": bool(suspicious_head),
            "suspicion_level": suspicion_level,
            "suspicion_score": suspicion_numeric,
        },
        flush=True,
    )

    if get_settings().DEBUG:
        logger.debug(
            "[PROCTORING FINAL SCORE] %s",
            {
                "phone_effective": bool(phone_effective),
                "suspicious_head": bool(suspicious_head),
                "suspicion_score": suspicion_numeric,
                "suspicion_risk_level": suspicion_level,
            },
        )

    stress_bh = float(stress_for_label) if stress_for_label is not None else 0.0
    conf_bh = float(conf_for_label) if conf_for_label is not None else 0.0
    behavioral_analysis = {
        "visual": gaze_professional,
        "stress": (
            "Signes de stress potentiels (stress estimé élevé et mouvements fréquents)."
            if stress_bh >= 62 and rapid >= 8
            else "Stress estimé modéré ; vigilance si hésitations visibles dans certaines réponses."
            if stress_bh >= 38
            else "Stress estimé faible ; comportement relativement stable."
        ),
        "confidence": (
            "Confiance perçue élevée (stabilité session + indicateurs de confiance)."
            if conf_bh >= 72 and off_ratio <= 0.3
            else "Confiance perçue modérée ; marge de progression possible dans l’aisance à l’oral."
            if conf_bh >= 52
            else "Confiance perçue plutôt faible ; réponses potentiellement plus hésitantes."
        ),
        "suspicion": suspicion_professional,
    }

    cand_row = (
        db.query(Candidat.prenom, Candidat.nom)
        .join(Candidature, Candidature.candidat_id == Candidat.id)
        .filter(Candidature.id == test_oral.id_candidature)
        .first()
    )
    cand_prenom = (cand_row[0] or "").strip() if cand_row else ""
    cand_nom = (cand_row[1] or "").strip() if cand_row else ""
    cand_display = _fetch_candidate_display_name(db, test_oral)

    return {
        "candidature_id": str(candidature_id),
        "offre_titre": offre_titre,
        "candidate_prenom": cand_prenom or None,
        "candidate_nom": cand_nom or None,
        "candidate_display_name": cand_display,
        "test_oral": test_payload,
        "questions": questions_out,
        "cheating_flags": test_oral.cheating_flags,
        "timeline": format_timeline_entries(flags, test_oral.started_at),
        "primary_snapshot_url": primary_snapshot_url(flags),
        "candidate_photo_url": photo_rel,
        "candidate_image_url": select_candidate_snapshot_url(flags),
        "badge": {
            "badge_key": ai.get("badge_key"),
            "badge_display": ai.get("badge_display"),
            "source": ai.get("source"),
            "synthesis_badge_key": ai.get("synthesis_badge_key"),
        },
        "ai_summary": ai.get("summary", ""),
        "ai_report": {
            "visual_behavior": ai.get("visual_behavior", ""),
            "stress_assessment": ai.get("stress_assessment", ""),
            "confidence_assessment": ai.get("confidence_assessment", ""),
            "suspicion_assessment": ai.get("suspicion_assessment", ""),
            "conclusion": ai.get("conclusion", ""),
            "strengths": ai.get("strengths") or [],
            "weaknesses": ai.get("weaknesses") or [],
            "recommendation": ai.get("recommendation", ""),
            "decision_reason": ai.get("decision_reason", ""),
            "risk_notes": ai.get("risk_notes", ""),
        },
        "proctoring_insights": proctoring_insights,
        "behavioral_analysis": behavioral_analysis,
    }
