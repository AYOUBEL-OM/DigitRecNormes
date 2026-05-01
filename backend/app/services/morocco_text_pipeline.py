"""
Pipeline obligatoire après toute génération LLM (QCM, exercice, feedback) :
sanitize → validate → normalize (prose uniquement).

Garantit l’absence de devises interdites dans les champs contrôlés et des montants DH plausibles.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from app.constants.morocco_context import MAX_DH_AMOUNT_NORMALIZED

logger = logging.getLogger(__name__)

Mode = Literal["prose", "code"]

# Montants suivis de DH ou MAD (espaces / points / virgules comme séparateurs de milliers)
_RE_DH_AMOUNT = re.compile(
    r"(?P<num>\d[\d\s\.\u202f\u00A0,]*)\s*(?P<cur>DH|MAD|dirhams?)\b",
    re.IGNORECASE,
)

# Dollar utilisé comme devise (pas les $ de template bash / regex rares en code — géré par mode)
_RE_USD_LIKE = re.compile(
    r"(?<![A-Za-z0-9_])\$\s*[\d]|[\d]\s*\$|(?<![A-Za-z])\$\s*(?:USD|EUR|£)",
    re.IGNORECASE,
)


def sanitize_currency(text: str) -> tuple[str, list[str]]:
    """
    Remplace €, EUR, « euros » par DH / dirhams. Ne lève pas d’exception.
    Retourne (texte, messages de log).
    """
    if not text:
        return text, []
    logs: list[str] = []
    out = text

    if "€" in out or "\u20ac" in out:
        logs.append("Currency corrected: euro symbol → DH")
        out = out.replace("\u20ac", "€")
        out = re.sub(r"(\d[\d\s\.,\u202f\u00A0]*)\s*€", r"\1 DH", out)
        out = out.replace("€", " DH ")

    if re.search(r"\bEUR\b", out, re.I):
        logs.append("Currency corrected: EUR → DH")
        out = re.sub(r"\bEUR\b", "DH", out, flags=re.I)

    if re.search(r"\beuros?\b", out, re.I):
        logs.append("Currency corrected: euros → dirhams")
        out = re.sub(r"\beuros?\b", "dirhams", out, flags=re.I)

    if re.search(r"\bUSD\b", out, re.I):
        logs.append("Currency corrected: USD → DH")
        out = re.sub(r"\bUSD\b", "DH", out, flags=re.I)

    # Montants style $ 1 200 ou $1200 (devise USD) → DH
    new_usd = re.sub(
        r"(?<![A-Za-z0-9_])\$\s*(\d[\d\s\.,\u202f\u00A0]*)",
        r"\1 DH",
        out,
    )
    if new_usd != out:
        logs.append("Currency corrected: $ amount → DH")
        out = new_usd

    # Livre sterling résiduelle
    if "£" in out:
        logs.append("Currency corrected: £ → DH")
        out = re.sub(r"(\d[\d\s\.,\u202f\u00A0]*)\s*£", r"\1 DH", out)
        out = out.replace("£", " DH ")

    out = re.sub(r"\s{2,}", " ", out).strip()
    return out, logs


def _parse_frenchish_int(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    # Garder chiffres uniquement pour robustesse
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def normalize_moroccan_amounts(text: str) -> tuple[str, list[str]]:
    """
    Plafonne les montants explicitement en DH/MAD au-dessus de MAX_DH_AMOUNT_NORMALIZED.
    Retourne (texte, logs).
    """
    if not text:
        return text, []
    logs: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        raw_num = m.group("num")
        cur = m.group("cur")
        n = _parse_frenchish_int(raw_num)
        if n is None or n <= MAX_DH_AMOUNT_NORMALIZED:
            return m.group(0)
        new_n = MAX_DH_AMOUNT_NORMALIZED
        logs.append(f"Amount normalized from {n} to {new_n} DH")
        # Format lisible type français : espaces milliers
        fmt = f"{new_n:,}".replace(",", " ")
        return f"{fmt} {cur}"

    out = _RE_DH_AMOUNT.sub(_repl, text)
    return out, logs


def validate_currency(text: str, *, mode: Mode = "prose") -> None:
    """
    Lève ValueError si une devise interdite subsiste après sanitization.
    En mode ``code`` : n’applique pas la contrainte sur ``$`` (jQuery, bash, etc.).
    """
    if not text:
        return
    if "€" in text or "\u20ac" in text:
        raise ValueError("Invalid currency detected: euro symbol (€) in text after sanitization")
    if re.search(r"\bEUR\b", text, re.I):
        raise ValueError("Invalid currency detected: EUR token in text after sanitization")
    if "£" in text:
        raise ValueError("Invalid currency detected: £ in text after sanitization")

    if mode == "prose":
        if _RE_USD_LIKE.search(text):
            raise ValueError("Invalid currency detected: USD-style $ in prose text")
        if re.search(r"\bUSD\b", text, re.I):
            raise ValueError("Invalid currency detected: USD token in prose text")


def run_morocco_pipeline(text: str, *, mode: Mode = "prose") -> tuple[str, list[str]]:
    """
    Ordre : sanitize → validate → normalize (normalize uniquement en prose).

    Retourne (texte final, logs agrégés).
    """
    all_logs: list[str] = []
    t, ls = sanitize_currency(text)
    all_logs.extend(ls)

    validate_currency(t, mode=mode)

    if mode == "prose":
        t, ln = normalize_moroccan_amounts(t)
        all_logs.extend(ln)

    for msg in all_logs:
        logger.info("morocco_text_pipeline: %s", msg)

    return t, all_logs


def apply_pipeline_to_quiz_payload(data: dict) -> dict:
    """
    Parcourt récursivement un dict JSON de quiz (QCM ou EXERCICE) et applique le pipeline
    sur toutes les chaînes. Clés considérées comme code : ``initial_code`` (pas de normalize montants).
    """
    code_keys = frozenset({"initial_code", "initialcode"})

    def _walk(obj: object, key: str | None = None) -> object:
        if isinstance(obj, dict):
            return {str(k): _walk(v, str(k)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(x, key) for x in obj]
        if isinstance(obj, str):
            m: Mode = "code" if (key and key.lower() in code_keys) else "prose"
            new_s, logs = run_morocco_pipeline(obj, mode=m)
            return new_s
        return obj

    return _walk(data)  # type: ignore[return-value]


def apply_pipeline_to_oral_question(text: str) -> str:
    """Une question d’entretien oral : toujours traitée comme prose."""
    new_s, _ = run_morocco_pipeline(text, mode="prose")
    return new_s
