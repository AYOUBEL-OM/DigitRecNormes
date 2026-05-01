"""
Normalisation des réponses QCM : lettre (A/B/…), index, ou texte d'option — comparaison robuste.

Utilisé à la soumission (recalcul du snapshot + score) et à l'affichage rapport (anciens snapshots).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LETTER_RE = re.compile(r"^\s*([A-Za-z])\s*$")
_PREFIX_LETTER_RE = re.compile(r"^\s*([A-Za-z])\s*[\.\)]\s*(.+)$", re.DOTALL)


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _strip_option_prefix(s: str) -> str:
    """« A. foo » / « a) foo » -> « foo » ; sinon trim."""
    t = (s or "").strip()
    m = _PREFIX_LETTER_RE.match(t)
    if m:
        return m.group(2).strip()
    return t


def normalize_qcm_answer(value: Any, options: Optional[list[Any]]) -> str:
    """
    Retourne une clé de comparaison : texte d'option normalisé (minuscules, sans accents, espaces collapsed).

    - Lettre seule A..Z : mappe vers options[index] si disponible.
    - Entier 0..n-1 : mappe vers options[i].
    - Chaîne numérique « 0 »..« n-1 » : idem.
    - Sinon : texte brut (préfixe A. / a) retiré si présent).
    """
    opts = [str(o) for o in (options or []) if o is not None]
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        if 0 <= value < len(opts):
            return _collapse_ws(_strip_diacritics(_strip_option_prefix(opts[value]).lower()))
        return _collapse_ws(_strip_diacritics(str(value).lower()))
    s = str(value).strip()
    if not s:
        return ""

    m = _LETTER_RE.match(s)
    if m and opts:
        idx = ord(m.group(1).upper()) - ord("A")
        if 0 <= idx < len(opts):
            raw = _strip_option_prefix(opts[idx])
            return _collapse_ws(_strip_diacritics(raw.lower()))

    if s.isdigit() and opts:
        idx = int(s)
        if 0 <= idx < len(opts):
            raw = _strip_option_prefix(opts[idx])
            return _collapse_ws(_strip_diacritics(raw.lower()))

    raw = _strip_option_prefix(s)
    return _collapse_ws(_strip_diacritics(raw.lower()))


def qcm_answers_equivalent(candidate: Any, expected: Any, options: Optional[list[Any]]) -> bool:
    opts = [str(o) for o in (options or []) if o is not None]
    ca = normalize_qcm_answer(candidate, opts)
    ea = normalize_qcm_answer(expected, opts)
    if not ca or not ea:
        return False
    return ca == ea


def resolve_option_index(expected: Any, options: list[Any]) -> Optional[int]:
    """Index de l'option « correcte » à partir de la valeur attendue (lettre, index, ou texte)."""
    opts = [str(o) for o in options if o is not None]
    if not opts:
        return None
    if isinstance(expected, int) and 0 <= expected < len(opts):
        return expected
    s = str(expected).strip() if expected is not None else ""
    if not s:
        return None
    m = _LETTER_RE.match(s)
    if m:
        idx = ord(m.group(1).upper()) - ord("A")
        if 0 <= idx < len(opts):
            return idx
    if s.isdigit():
        idx = int(s)
        if 0 <= idx < len(opts):
            return idx
    target = normalize_qcm_answer(s, opts)
    for i, opt in enumerate(opts):
        if normalize_qcm_answer(opt, opts) == target:
            return i
    return None


def option_letter_from_index(idx: int) -> Optional[str]:
    if 0 <= idx <= 25:
        return chr(ord("A") + idx)
    return None


def correct_answer_display(expected: Any, options: list[Any]) -> str:
    """Texte lisible + lettre entre parenthèses si on peut la déduire."""
    opts = [str(o) for o in options if o is not None]
    idx = resolve_option_index(expected, opts)
    if idx is not None and 0 <= idx < len(opts):
        text = _strip_option_prefix(opts[idx])
        letter = option_letter_from_index(idx)
        if letter:
            return f"{text} ({letter})"
        return text
    return str(expected).strip() if expected is not None else "—"


def candidate_answer_display(candidate: Any, options: list[Any]) -> str:
    """Affichage : toujours préférer le libellé de l'option si la valeur est une lettre / index."""
    opts = [str(o) for o in options if o is not None]
    if candidate is None or str(candidate).strip() == "":
        return "—"
    idx = resolve_option_index(candidate, opts)
    if idx is not None and 0 <= idx < len(opts):
        return _strip_option_prefix(opts[idx])
    return str(candidate).strip()


def qcm_correction_debug_payload(
    question_text: Any,
    candidate_raw: Any,
    correct_raw: Any,
    options: list[Any],
    is_correct: bool,
) -> dict[str, Any]:
    opts = [str(o) for o in options if o is not None]
    return {
        "question": (str(question_text)[:200] + "…") if len(str(question_text)) > 200 else str(question_text),
        "candidate_raw": candidate_raw,
        "correct_raw": correct_raw,
        "candidate_normalized": normalize_qcm_answer(candidate_raw, opts),
        "correct_normalized": normalize_qcm_answer(correct_raw, opts),
        "is_correct": is_correct,
    }


def recompute_qcm_snapshot_v1(detail_snapshot: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """
    Recalcule status / score_label / score pour un snapshot version=1, quiz_kind=qcm.
    Retourne (snapshot_muté, score_0_100).
    """
    snap = dict(detail_snapshot)
    qcm = snap.get("qcm")
    if not isinstance(qcm, dict):
        return snap, 0.0
    items = qcm.get("items")
    if not isinstance(items, list):
        return snap, 0.0

    new_items: list[dict[str, Any]] = []
    correct_n = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        row = dict(it)
        opts = row.get("options")
        opt_list = opts if isinstance(opts, list) else []
        cand = row.get("candidate_answer")
        exp = row.get("expected_answer")
        ok = qcm_answers_equivalent(cand, exp, opt_list)
        logger.info(
            "QCM CORRECTION DEBUG %s",
            qcm_correction_debug_payload(
                row.get("question_text"),
                cand,
                exp,
                opt_list,
                ok,
            ),
        )
        prev = str(row.get("status") or "").lower()
        if ok:
            row["status"] = "correct"
        elif prev == "partial":
            row["status"] = "partial"
        else:
            row["status"] = "incorrect"
        row["score_label"] = (
            "1 pt"
            if ok
            else ("0.5 pt" if row["status"] == "partial" else "0 pt")
        )
        if ok:
            correct_n += 1
        new_items.append(row)

    qcm = dict(qcm)
    qcm["items"] = new_items
    snap["qcm"] = qcm
    total = len(new_items)
    score = round((correct_n / total) * 100) if total else 0.0
    return snap, float(score)
