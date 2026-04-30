"""
Transcription entretien oral — **Groq Whisper** (tentatives multiples, modèle de secours).

- Consigne verbatim via `_build_verbatim_asr_prompt` (vocabulaire question ; langue parlée = langue écrite).
- Jusqu’à 3 appels ASR (délai entre tentatives ; 3ᵉ tentative avec un autre modèle Whisper Groq).
- Post-traitement : `validate_transcript_quality`, normalisation Unicode minimale,
  `align_proper_names_from_context` (sans inventer).
- Échecs typés : ``[AUDIO EMPTY OR CORRUPTED]``, ``[TRANSCRIPTION PROVIDER ERROR]``,
  ``[AUDIO UNCLEAR OR SILENT]`` (+ détail qualité si rejet heuristique).

Normalisation audio : ffmpeg → WAV mono 16 kHz si disponible.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
import unicodedata
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral
from app.services.oral_insights_storage import (
    SESSION_SCORES_KEY,
    get_answer_insight,
)
from app.services.oral_proctoring import (
    build_flags_global_summary,
    compute_eye_contact_score_global_from_flags,
    compute_gaze_off_ratio,
    compute_gaze_quality,
    compute_movement_level,
    compute_presence_stability,
    compute_suspicion_assessment,
    ensure_oral_proctoring_fields,
    merge_proctoring_estimates_enriched,
    normalize_proctoring_flags,
    refresh_suspicious_movements_count_from_flags,
)

logger = logging.getLogger(__name__)

SOURCE_GROQ = "groq"
SOURCE_FAILED = "failed"
SOURCE_MOCK = "mock"

# Texte stocké si aucun moteur ASR n’a produit de transcript exploitable (jamais silencieux).
TRANSCRIPTION_FAILED_MARKER = "[TRANSCRIPTION FAILED]"
TRANSCRIPTION_AUDIO_EMPTY_MARKER = "[AUDIO EMPTY OR CORRUPTED]"
TRANSCRIPTION_PROVIDER_ERROR_MARKER = "[TRANSCRIPTION PROVIDER ERROR]"
TRANSCRIPTION_AUDIO_UNCLEAR_MARKER = "[AUDIO UNCLEAR OR SILENT]"
# Fichier lisible mais trop petit pour être crédible comme enregistrement vocal (hors en-tête seul).
ASR_MIN_FILE_BYTES_TRY = 64
ASR_VERY_SMALL_BYTES_WARN = 512

FILLER_RE = re.compile(
    r"\b(euh+|heu+|hum+|hmm+|bah+|ben+|voilà|donc|genre|en fait|un peu|comment dire)\b",
    re.IGNORECASE,
)
HESITATION_MARKERS = re.compile(
    r"\b(je sais pas|je ne sais pas|peut-être|maybe|perhaps|wallah|yani|شي|ما عرفت)\b",
    re.IGNORECASE,
)

# Darija / maghrébin (Latin + arabe) — indices pour classifier hors MSA pure
_DARIJA_LATIN_MARKERS = re.compile(
    r"\b(wach|wash|daba|bzaf|3lach|ch7al|chno|chnowa|fin|fayn|"
    r"nta|nti|ntoma|ntouma|7na|dial|diali|dialk|diali|mzyan|mzian|mezyan|zwin|"
    r"wakha|saf|safi|khouya|lalla|sidi|drari|walid|walida|had|hadak|hadik|"
    r"ma3ndich|maendich|labas|labass|chouf|bach|bghit|kan|kay|ghadi|ghayt|"
    r"ydir|dir|tsawer|s7ab|s7abi|wfik|wfik|kidayr|kidayra|3ndk|t3ref|fhem|"
    r"chno|chnowa|weld|mezyan|makayn|kayn|ghir|bach)\b",
    re.IGNORECASE,
)
_DARIJA_ARABIC_MARKERS = re.compile(
    r"(واش|شنو|شحال|دابا|بزاف|علاش|فين|واخا|مزيان|هاداك|ديال|"
    r"خويا|والو|عندي|كن|كان|غادي|بغيت|شفت|شوف|دير|ديرو|شوف|شوفو|"
    r"بغيت|بغيتي|علاش|عليه|هادا|هادي|هادو|لي|ليش|كيدير|كاين|ماكاينش)",
    re.IGNORECASE,
)
# Fragments plus « MSA » en écriture arabe (réduit les faux positifs darija)
_MSA_AR_SCRIPT_MARKERS = re.compile(
    r"(الذي|اللاتي|حيث|إنّ|أنّ|لأن|لِأن|بالنسبة|وفقا|وفقًا|بالإضافة|عليه|عموما|عمومًا|"
    r"هناك|لذلك|أيضا|أيضًا|بخصوص)",
    re.IGNORECASE,
)

_ASR_VERBATIM_INSTRUCTION = (
    "Verbatim transcription. Output exactly what is spoken, in that same language. "
    "Do not translate. Do not paraphrase. Do not answer the question. "
    "French must stay strictly French; English must stay strictly English — no cross-language normalization. "
    "If the speaker uses Moroccan Darija, transcribe in Darija (keep colloquial form). "
    "If Modern Standard Arabic, transcribe in Arabic. "
    "Do not mix languages without cause. "
    "The text below is the interview question for spelling context only (names, job title)."
)

_ASR_PROMPT_MAX_LEN = 550

_LATIN_SHORT_OK = frozenset(
    {
        "le",
        "la",
        "un",
        "de",
        "et",
        "en",
        "il",
        "on",
        "au",
        "du",
        "je",
        "tu",
        "me",
        "te",
        "se",
        "ce",
        "ne",
        "si",
        "l",
        "d",
        "qu",
        "n",
        "y",
        "a",
        "the",
        "an",
        "in",
        "at",
        "to",
        "of",
        "is",
        "it",
        "we",
        "he",
        "be",
        "or",
        "if",
        "my",
        "so",
        "no",
        "do",
        "go",
        "up",
        "by",
        "as",
    }
)

_VOWEL_LATIN = re.compile(r"[aeiouyàâäéèêëïîôùûüæœ]", re.I)


def _latin_dominant_for_fr_en_checks(t: str) -> bool:
    ar = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F]", t))
    lat = len(re.findall(r"[A-Za-z\u00C0-\u024F]", t))
    if lat + ar < 6:
        return False
    return lat >= ar * 2.5 and ar <= max(3, lat // 12)


def _latin_token_looks_plausible(tok: str) -> bool:
    x = re.sub(r"^['\-]+|['\-]+$", "", tok)
    if len(x) <= 1:
        return False
    low = x.lower()
    if low in _LATIN_SHORT_OK:
        return True
    if len(x) > 4 and not _VOWEL_LATIN.search(x):
        return False
    cons = sum(1 for c in low if c.isalpha() and c not in "aeiouyàâäéèêëïîôùûüæœ")
    if len(x) >= 5 and cons / max(len(x), 1) > 0.88:
        return False
    if len(x) >= 4 and re.search(r"(.)\1{3,}", low):
        return False
    return True


def _validate_latin_fr_en_extra(t: str) -> tuple[bool, str]:
    tokens = re.findall(r"[A-Za-z\u00C0-\u024F]+(?:'[A-Za-z\u00C0-\u024F]+)?", t)
    if len(tokens) < 6:
        return True, "ok"
    ok_n = sum(1 for w in tokens if _latin_token_looks_plausible(w))
    ratio = ok_n / len(tokens)
    if ratio < 0.38:
        return False, f"low_plausible_latin_token_ratio({ratio:.2f})"

    low_t = t.lower()
    if re.search(r"\b(\w{2,})\s+\1\s+\1\s+\1\b", low_t):
        return False, "repeated_word_quad"

    if len(tokens) >= 10:
        bigrams = [
            f"{tokens[i].lower()} {tokens[i + 1].lower()}"
            for i in range(len(tokens) - 1)
        ]
        mc, cnt = Counter(bigrams).most_common(1)[0]
        if cnt >= 5 and cnt / len(bigrams) > 0.42:
            return False, "repeated_bigram_pattern"

    return True, "ok"


def _log_quality_check(text: str, duration_seconds: int, ok: bool, reason: str) -> None:
    t = (text or "").strip()
    print(
        "QUALITY CHECK:",
        {
            "text_length": len(t),
            "duration": duration_seconds,
            "quality_ok": ok,
            "reason": reason,
        },
        flush=True,
    )


def validate_transcript_quality(text: str, duration_seconds: int = 1) -> tuple[bool, str]:
    """
    Contrôle anti-garbage (dont heuristiques douces pour latin FR/EN).
    Assoupli pour réponses orales courtes (< 10 s) et textes > 10 caractères.
    Retourne (valid, reason).
    """
    t = (text or "").strip()
    dur = max(1, min(int(duration_seconds or 1), 600))

    if not t:
        _log_quality_check(text, dur, False, "empty")
        return False, "empty"

    # Transcript déjà assez long : ne pas sur-filtrer (parole réelle).
    if len(t) > 10:
        _log_quality_check(text, dur, True, "ok_len_gt_10")
        return True, "ok_len_gt_10"

    # Réponses courtes : éviter les rejets agressifs (Whisper peut produire peu de texte pour 8 s).
    if dur < 10 and len(t) >= 2:
        _log_quality_check(text, dur, True, "ok_short_duration_bypass")
        return True, "ok_short_duration_bypass"

    min_chars = 2
    if dur >= 12:
        min_chars = 6
    if dur >= 25:
        min_chars = 10
    if dur >= 45:
        min_chars = 14
    if len(t) < min_chars:
        _log_quality_check(text, dur, False, f"too_short(len={len(t)},min_for_duration={min_chars})")
        return False, f"too_short(len={len(t)},min_for_duration={min_chars})"

    letters = len(re.findall(r"[A-Za-z\u00C0-\u024F\u0600-\u06FF\u0750-\u077F]", t))
    non_space = len(re.sub(r"\s+", "", t))
    ratio_floor = 0.14 if dur < 20 else 0.18
    if non_space > 0 and letters / non_space < ratio_floor:
        _log_quality_check(text, dur, False, "low_readable_ratio")
        return False, "low_readable_ratio"

    if t.count("\ufffd") >= 2:
        _log_quality_check(text, dur, False, "encoding_garbage")
        return False, "encoding_garbage"

    if re.search(r"[\u0400-\u04FF\u0E00-\u0E7F\u4E00-\u9FFF]", t):
        _log_quality_check(text, dur, False, "unexpected_script")
        return False, "unexpected_script"

    ar_count = len(re.findall(r"[\u0600-\u06FF]", t))
    lat_count = len(re.findall(r"[A-Za-z\u00C0-\u024F]", t))
    if lat_count >= 12 and ar_count >= 4 and ar_count / max(lat_count, 1) > 0.18:
        _log_quality_check(text, dur, False, "suspicious_latin_arabic_mix")
        return False, "suspicious_latin_arabic_mix"

    words = re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I)
    if len(words) >= 8:
        mc, cnt = Counter(w.lower() for w in words).most_common(1)[0]
        if cnt >= max(7, len(words) * 0.55) and len(words) <= 40:
            _log_quality_check(text, dur, False, "excessive_repetition")
            return False, "excessive_repetition"

    if _latin_dominant_for_fr_en_checks(t):
        ok_x, reason_x = _validate_latin_fr_en_extra(t)
        if not ok_x:
            if dur < 12 and len(t) <= 80:
                _log_quality_check(text, dur, True, f"ok_latin_relaxed_short_answer({reason_x})")
                return True, "ok_latin_relaxed_short_answer"
            _log_quality_check(text, dur, False, reason_x)
            return False, reason_x

    _log_quality_check(text, dur, True, "ok")
    return True, "ok"


@dataclass
class TranscriptionOutcome:
    text: str
    source: str
    language: str | None
    confidence: float | None
    # Code langue brut renvoyé par Whisper (verbose_json), si applicable.
    whisper_language_raw: str | None = None
    # Heuristique surface (fr|en|ar|darija|unknown) sur le texte — équivalent « langue détectée ».
    detected_surface_lang: str | None = None
    # Journal des tentatives ASR (diagnostic route / logs).
    attempts_log: list[dict[str, Any]] = field(default_factory=list)


def _groq_api_key(settings: Settings) -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip() or (settings.GROQ_API_KEY or "").strip()


def _question_language_tiebreak(question_text: str | None, transcript: str) -> str | None:
    """
    Indice optionnel depuis la question si le transcript est court / ambigu (métadonnées seulement).
    N’applique pas si la question est surtout en arabe (évite de forcer fr/en sur une réponse arabe).
    """
    if not question_text or len((transcript or "").strip()) > 100:
        return None
    q = question_text.strip()
    if len(re.findall(r"[\u0600-\u06FF]", q)) >= 12:
        return None
    fr_h = len(
        re.findall(
            r"\b(le|la|les|des|une|pour|avec|comment|votre|notre|cette|être|donc)\b",
            q,
            re.I,
        )
    )
    en_h = len(
        re.findall(
            r"\b(the|and|with|what|why|your|describe|about|this|that|have|from)\b",
            q,
            re.I,
        )
    )
    if fr_h >= 3 and fr_h >= en_h + 2:
        return "fr"
    if en_h >= 3 and en_h >= fr_h + 2:
        return "en"
    return None


def _classify_fr_en_latin(t: str, question_text: str | None) -> str:
    """
    Distinction FR / EN sur texte principalement latin — évite les faux positifs si signal faible.
    """
    t = (t or "").strip()
    if len(t) < 2:
        return "unknown"

    fr_pat = len(
        re.findall(
            r"\b(le|la|les|des|du|de|un|une|et|est|être|vous|nous|dans|pour|avec|"
            r"comment|très|bien|aussi|cette|notre|votre|mais|donc|comme|sur|par|"
            r"plus|tout|tous|autre|fait|faire|avez|êtes|été|ai|as|ont|chez|rien|"
            r"pas|oui|non|quoi|alors|après|avant|depuis|encore|toujours|jamais)\b",
            t,
            re.I,
        )
    )
    en_pat = len(
        re.findall(
            r"\b(the|a|an|and|or|but|in|on|at|to|for|of|as|by|with|from|"
            r"this|that|these|those|what|when|where|which|who|whom|your|our|their|"
            r"have|has|had|was|were|been|being|would|could|should|very|also|just|"
            r"not|yes|no|then|there|here|they|them|she|her|his|its)\b",
            t,
            re.I,
        )
    )
    fr_chars = len(re.findall(r"[àâäéèêëïîôùûçœ]", t.lower()))
    en_ing = len(re.findall(r"\b[a-z]{3,}ing\b", t, re.I))
    en_ed = len(re.findall(r"\b[a-z]{3,}ed\b", t, re.I))

    fr_score = float(fr_pat) + fr_chars * 1.15 + (2.0 if re.search(r"\bqu'", t, re.I) else 0.0)
    en_score = float(en_pat) + en_ing * 0.55 + en_ed * 0.25

    margin = 1.45
    if len(t) < 14:
        hint = _question_language_tiebreak(question_text, t)
        if fr_chars >= 2:
            return "fr"
        if re.search(
            r"\b(my name is|i am|i'm|from morocco|from the|nice to meet|thank you|hello|hi there)\b",
            t,
            re.I,
        ):
            return "en"
        if re.search(
            r"\b(je m'appelle|je suis|j'habite|au maroc|merci|bonjour|salut)\b",
            t,
            re.I,
        ):
            return "fr"
        if re.search(
            r"\b(the|and|with|what|your|this|that|have|from|was|were|would)\b",
            t,
            re.I,
        ):
            return "en"
        if re.search(
            r"\b(le|la|les|des|vous|nous|pour|avec|comment|très|être)\b",
            t,
            re.I,
        ):
            return "fr"
        if hint:
            return hint
        if fr_score > 0 or en_score > 0:
            return "fr" if fr_score >= en_score else "en"
        return "fr"

    if abs(fr_score - en_score) < margin:
        hint = _question_language_tiebreak(question_text, t)
        if hint:
            return hint
        return "fr" if fr_score >= en_score else "en"

    return "fr" if fr_score > en_score else "en"


def detect_transcript_language(text: str, question_text: str | None = None) -> str:
    """
    Langue dominante du transcript (surface), sans appel externe.
    Codes : fr, en, ar (MSA dominant en écriture arabe), darija, unknown.
    `question_text` : aide uniquement pour cas ambigus (ne modifie pas le texte).
    """
    t = (text or "").strip()
    if len(t) < 2:
        return "unknown"
    ar_chars = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F]", t))
    lat_chars = len(re.findall(r"[A-Za-zÀ-ÿ]", t))
    total_letters = ar_chars + lat_chars + 1
    ar_ratio = ar_chars / total_letters

    if ar_ratio >= 0.35 or (ar_chars >= 12 and ar_ratio >= 0.2):
        msa_h = len(_MSA_AR_SCRIPT_MARKERS.findall(t))
        dar_ar = len(_DARIJA_ARABIC_MARKERS.findall(t))
        if dar_ar >= 2 and dar_ar >= msa_h:
            return "darija"
        if msa_h >= 2 and dar_ar == 0:
            return "ar"
        if _DARIJA_LATIN_MARKERS.search(t) or (dar_ar >= 1 and msa_h == 0):
            return "darija"
        return "ar"

    if lat_chars >= 5 and (
        _DARIJA_LATIN_MARKERS.search(t) or _DARIJA_ARABIC_MARKERS.search(t)
    ):
        return "darija"

    if lat_chars < 5:
        hint = _question_language_tiebreak(question_text, t)
        if hint:
            return hint
        if lat_chars >= 2:
            return _classify_fr_en_latin(t, question_text)
        return "unknown"

    return _classify_fr_en_latin(t, question_text)


def mock_transcribe(duration_seconds: int, question_text: str) -> str:
    words = (question_text or "").split()[:18]
    theme = " ".join(words) if words else "la question posée"
    return (
        f"Réponse orale enregistrée (durée indicative {duration_seconds}s). "
        f"Le candidat développe des éléments en lien avec : {theme}."
    )


def _is_transcription_failed_marker(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t == TRANSCRIPTION_FAILED_MARKER or t.startswith(f"{TRANSCRIPTION_FAILED_MARKER}"):
        return True
    for prefix in (
        TRANSCRIPTION_AUDIO_EMPTY_MARKER,
        TRANSCRIPTION_PROVIDER_ERROR_MARKER,
        TRANSCRIPTION_AUDIO_UNCLEAR_MARKER,
    ):
        if t.startswith(prefix):
            return True
    return False


def _is_mock_transcript(text: str) -> bool:
    return (text or "").strip().startswith("Réponse orale enregistrée")


def prepare_audio_path_for_asr(src: Path) -> tuple[Path, bool]:
    """
    Si ffmpeg est disponible, convertit en WAV PCM mono 16 kHz (format stable pour Whisper).
    Retourne (chemin_à_lire, temporaire_à_supprimer).
    """
    if not src.is_file() or src.stat().st_size < 100:
        return src, False
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return src, False
    tmp_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp_path = Path(name)
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src.resolve()),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if not tmp_path.is_file() or tmp_path.stat().st_size < 200:
            tmp_path.unlink(missing_ok=True)
            return src, False
        return tmp_path, True
    except Exception as exc:
        logger.debug("prepare_audio_path_for_asr: ffmpeg indisponible ou échec — %s", exc)
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return src, False


def _mime_for_audio(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext, "audio/webm")


def transcribe_with_groq(
    audio_path: Path,
    settings: Settings,
    language: str | None = None,
    prompt: str | None = None,
    *,
    model: str | None = None,
) -> tuple[str | None, str | None, float | None, str | None]:
    """
    Whisper via Groq (seul moteur ASR).
    Retourne (text, lang, conf, err) où ``err`` est non ``None`` en cas d’échec (message court).
    """
    api_key = _groq_api_key(settings)
    if not api_key:
        logger.error("Groq transcription failed: GROQ_API_KEY missing")
        return None, None, None, "groq_api_key_missing"
    if not audio_path.is_file():
        logger.error("Groq transcription failed: audio file not found: %s", audio_path.resolve())
        return None, None, None, "audio_file_not_found"
    try:
        data = audio_path.read_bytes()
    except OSError as exc:
        logger.error("Groq transcription failed: cannot read file: %s", exc)
        return None, None, None, f"os_read_error:{exc!r}"
    if len(data) == 0:
        logger.error("Groq transcription failed: empty file (0 bytes)")
        return None, None, None, "empty_file_bytes"
    if len(data) < ASR_MIN_FILE_BYTES_TRY:
        logger.warning(
            "Groq transcription: very small file (%s bytes) — attempting ASR anyway",
            len(data),
        )
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        model_eff = (model or settings.GROQ_WHISPER_MODEL or "whisper-large-v3-turbo").strip()
        base_kw: dict = {"model": model_eff, "temperature": 0.0}
        if language:
            base_kw["language"] = language
        if prompt:
            base_kw["prompt"] = prompt[:_ASR_PROMPT_MAX_LEN]
        try:
            transcription = client.audio.transcriptions.create(
                file=(audio_path.name, data),
                response_format="verbose_json",
                **base_kw,
            )
        except Exception:
            transcription = client.audio.transcriptions.create(
                file=(audio_path.name, data),
                **base_kw,
            )
        text = (getattr(transcription, "text", None) or "").strip()
        if not text:
            logger.error("Groq transcription failed: API returned empty text")
            return None, None, None, "groq_empty_text_response"
        lang = getattr(transcription, "language", None)
        conf = None
        segs = getattr(transcription, "segments", None) or []
        if segs:
            probs = [
                getattr(s, "avg_logprob", None)
                for s in segs
                if getattr(s, "avg_logprob", None) is not None
            ]
            if probs:
                avg_lp = sum(probs) / len(probs)
                conf = max(0.0, min(100.0, (avg_lp + 1.0) * 55))
        return text, (str(lang).lower() if lang else None), conf, None
    except Exception as exc:
        logger.error("Groq transcription failed: %s", exc)
        return None, None, None, f"groq_exception:{exc!r}"


def _heuristic_to_stored_code(det: str) -> str:
    return {
        "fr": "fr",
        "en": "en",
        "ar": "ar_msa",
        "darija": "ar_darija",
        "unknown": "unknown",
    }.get(det, "unknown")


def _normalize_whisper_lang_to_stored(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).lower().strip()
    if s in ("arabic", "ar"):
        return "ar_msa"
    if s in ("french", "fr"):
        return "fr"
    if s in ("english", "en"):
        return "en"
    if len(s) == 2 and s in ("fr", "en", "ar"):
        return {"fr": "fr", "en": "en", "ar": "ar_msa"}[s]
    return None


def _finalize_stored_language(
    transcript: str,
    whisper_lang: str | None,
    question_text: str | None = None,
) -> str:
    det = detect_transcript_language(transcript, question_text)
    h = _heuristic_to_stored_code(det)
    if h != "unknown":
        return h
    wn = _normalize_whisper_lang_to_stored(whisper_lang)
    if wn:
        return wn
    tstrip = (transcript or "").strip()
    if len(tstrip) >= 1:
        ar_n = len(re.findall(r"[\u0600-\u06FF]", tstrip))
        lat_n = len(re.findall(r"[A-Za-zÀ-ÿ]", tstrip))
        if ar_n > lat_n * 1.2:
            return "ar_msa"
        return "fr"
    return "fr"


def _language_from_text_heuristic(text: str) -> str:
    """Compat : codes stockés historiques (fr, en, ar_msa, ar_darija, unknown)."""
    return _finalize_stored_language(text, None, None)


def _build_verbatim_asr_prompt(question_text: str) -> str:
    """Prompt Whisper : consignes verbatim + question pour vocabulaire (noms, poste), sans forcer la langue."""
    head = _ASR_VERBATIM_INSTRUCTION + "\n---\n"
    q = (question_text or "").strip().replace("\r", " ").replace("\n", " ")
    q = re.sub(r"\s+", " ", q)
    if not q:
        return head[:_ASR_PROMPT_MAX_LEN]
    room = max(0, _ASR_PROMPT_MAX_LEN - len(head))
    return (head + q[:room])[:_ASR_PROMPT_MAX_LEN]


def _align_latin_proper_names_from_question(transcript: str, question_text: str) -> str:
    """
    Harmonise uniquement la graphie/casse de noms propres latins déjà présents dans la question,
    si une correspondance insensible à la casse existe dans le transcript (sans inventer de mots).
    """
    t = transcript or ""
    q = (question_text or "").strip()
    if not t or len(q) < 4:
        return t
    for m in re.finditer(
        r"\b([A-ZÀ-Ÿ][a-zà-ÿ'-]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ'-]+)+)\b",
        q,
    ):
        ref = m.group(1).strip()
        if len(ref) < 4:
            continue
        pat = re.compile(re.escape(ref), re.I)
        if pat.search(t):
            t = pat.sub(ref, t)
    return t


_QUESTION_STOPWORDS_FR_EN = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "for",
        "with",
        "from",
        "this",
        "that",
        "your",
        "vous",
        "votre",
        "notre",
        "dans",
        "pour",
        "avec",
        "comment",
        "pourquoi",
        "quelle",
        "quel",
        "quels",
        "quelles",
        "une",
        "des",
        "les",
        "est",
        "être",
        "avez",
        "about",
        "describe",
        "explain",
        "what",
        "when",
        "where",
        "how",
        "why",
        "would",
        "could",
    }
)


def _important_terms_from_question(question_text: str) -> list[str]:
    """Termes latins saillants de la question (FR/EN) pour alignement conservateur."""
    q = (question_text or "").strip()
    if len(q) < 4:
        return []
    found: list[str] = []
    cap_word = re.compile(
        r"\b([A-Z\u00C0-\u017F][a-z\u00E0-\u017F0-9'-]{2,})\b"
        r"|\b([A-Z\u00C0-\u017F]{2,})\b"
    )
    for m in cap_word.finditer(q):
        w = (m.group(1) or m.group(2) or "").strip()
        if len(w) >= 3:
            found.append(w)
    lower_long = re.compile(r"\b[a-z\u00E0-\u017F]{5,}\b", re.I)
    for m in lower_long.finditer(q):
        w = m.group(0)
        if w.lower() not in _QUESTION_STOPWORDS_FR_EN:
            found.append(w)
    seen: set[str] = set()
    out: list[str] = []
    for w in sorted(found, key=len, reverse=True):
        k = w.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(w)
    return out[:24]


def _align_terms_from_question_list(transcript: str, terms: list[str]) -> str:
    t = transcript or ""
    for ref in terms:
        if len(ref) < 4:
            continue
        pat = re.compile(re.escape(ref), re.I)
        if pat.search(t):
            t = pat.sub(ref, t)
    return t


def align_proper_names_from_context(
    transcript: str,
    question_text: str,
    *,
    candidate_name: str | None = None,
    job_title: str | None = None,
    city: str | None = None,
    company: str | None = None,
) -> str:
    """
    Harmonise graphie/casse de noms propres déjà présents dans le transcript,
    à partir de la question et de métadonnées optionnelles — sans inventer de mots.
    """
    t = _align_latin_proper_names_from_question(transcript or "", question_text or "")
    t = _align_terms_from_question_list(t, _important_terms_from_question(question_text))
    extras: list[str] = []
    for x in (candidate_name, job_title, city, company):
        s = (x or "").strip()
        if len(s) >= 3:
            extras.append(s)
    extras.sort(key=len, reverse=True)
    for phrase in extras:
        if len(phrase) >= 4:
            pat = re.compile(re.escape(phrase), re.I)
            if pat.search(t):
                t = pat.sub(phrase, t)
        for tok in re.split(r"[\s,;/]+", phrase):
            tok = tok.strip(".,;:!?\"'()[]")
            if len(tok) < 3:
                continue
            if not re.match(r"^[A-Za-z\u00C0-\u024F0-9'\-]+$", tok):
                continue
            pat = re.compile(r"\b" + re.escape(tok) + r"\b", re.I)
            if pat.search(t):
                t = pat.sub(tok, t)
    return t


def _levenshtein_distance(a: str, b: str) -> int:
    """Distance de Levenshtein (stdlib uniquement)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            ins, delete, sub = prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


_FUZZY_SKIP_TRANSCRIPT_WORDS = frozenset(
    _QUESTION_STOPWORDS_FR_EN
    | {
        "all",
        "any",
        "are",
        "bad",
        "big",
        "boy",
        "can",
        "did",
        "dix",
        "est",
        "far",
        "few",
        "for",
        "get",
        "got",
        "had",
        "has",
        "her",
        "him",
        "his",
        "how",
        "its",
        "let",
        "low",
        "may",
        "new",
        "non",
        "not",
        "now",
        "off",
        "old",
        "one",
        "our",
        "out",
        "oui",
        "own",
        "pas",
        "per",
        "que",
        "qui",
        "say",
        "see",
        "ses",
        "she",
        "six",
        "son",
        "sur",
        "ten",
        "the",
        "too",
        "top",
        "try",
        "two",
        "use",
        "vos",
        "was",
        "way",
        "who",
        "why",
        "yes",
        "yet",
        "you",
    }
)


def _latin_name_token(s: str) -> bool:
    return bool(re.match(r"^[A-Za-z\u00C0-\u024F0-9'\-]+$", s or ""))


def _scripts_compatible_for_fuzzy(token: str, ref: str) -> bool:
    """Évite de rapprocher un mot latin d’une référence arabe (ou l’inverse)."""
    t_ar = bool(re.search(r"[\u0600-\u06FF]", token or ""))
    r_ar = bool(re.search(r"[\u0600-\u06FF]", ref or ""))
    if t_ar != r_ar:
        return False
    if not r_ar and not _latin_name_token(token):
        return False
    return True


def _fuzzy_name_match_ok(token: str, ref_canon: str, tl: str, rl: str) -> bool:
    if tl == rl:
        return True
    if len(tl) < 3 or len(rl) < 3:
        return False
    if tl in _FUZZY_SKIP_TRANSCRIPT_WORDS:
        return False
    if not _scripts_compatible_for_fuzzy(token, ref_canon):
        return False
    if abs(len(tl) - len(rl)) > max(2, len(rl) // 3):
        return False
    d = _levenshtein_distance(tl, rl)
    ratio = SequenceMatcher(None, tl, rl).ratio()
    n = len(rl)
    if n <= 3:
        return d == 0
    if n == 4:
        return d <= 1 and ratio >= 0.9
    if n <= 8:
        return d <= 2 and ratio >= 0.88
    max_d = min(4, max(2, n // 5))
    return d <= max_d and ratio >= 0.86


def _collect_canonical_refs_from_context(context: dict[str, Any]) -> list[tuple[str, str]]:
    """Construit (graphie canonique, minuscule) pour comparaison fuzzy, sans doublons (préfère le plus long)."""
    chunks: list[str] = []
    for key in ("candidate_name", "job_title", "company_name", "city"):
        v = context.get(key)
        if isinstance(v, str) and v.strip():
            chunks.append(v.strip())
    qtxt = context.get("question_text")
    if isinstance(qtxt, str) and qtxt.strip():
        chunks.append(qtxt.strip())
        chunks.extend(_important_terms_from_question(qtxt))
    qk = context.get("question_keywords")
    if isinstance(qk, str) and qk.strip():
        chunks.extend(re.split(r"[\s,;/|]+", qk.strip()))
    elif isinstance(qk, (list, tuple)):
        for x in qk:
            if isinstance(x, str) and x.strip():
                chunks.append(x.strip())

    raw: list[str] = []
    for c in chunks:
        for part in re.split(r"[\s,;/|]+", c):
            t = part.strip(".,;:!?\"'()[]«»…")
            if len(t) >= 2:
                raw.append(t)

    by_lower: dict[str, str] = {}
    for tok in sorted(raw, key=len, reverse=True):
        low = tok.lower()
        if low not in by_lower or len(tok) > len(by_lower[low]):
            by_lower[low] = tok

    return [(canon, low) for low, canon in sorted(by_lower.items(), key=lambda x: len(x[1]), reverse=True)]


def _best_name_canonical(token: str, refs: list[tuple[str, str]]) -> str | None:
    tl = token.lower()
    best: str | None = None
    best_ratio = 0.0
    for canon, rl in refs:
        if tl == rl:
            return canon
        if not _fuzzy_name_match_ok(token, canon, tl, rl):
            continue
        ratio = SequenceMatcher(None, tl, rl).ratio()
        if ratio > best_ratio or (ratio == best_ratio and best and len(canon) > len(best)):
            best_ratio = ratio
            best = canon
    return best


def improve_names_from_context(transcript: str, context: dict[str, Any]) -> str:
    """
    Corrige uniquement la graphie des noms propres (personnes, lieux, entreprises, intitulés)
    lorsqu’un jeton du transcript est très proche d’une référence issue du contexte (fuzzy conservateur).
    Ne réécrit pas les phrases, ne traduit pas, ne change pas la langue.
    """
    t = transcript or ""
    if not t.strip() or not context:
        return t
    refs = _collect_canonical_refs_from_context(context)
    if not refs:
        return t

    token_re = re.compile(r"(?u)[\w'-]+")

    def repl(m: re.Match[str]) -> str:
        w = m.group(0)
        if len(w) < 2 or not any(ch.isalpha() for ch in w):
            return w
        cand = _best_name_canonical(w, refs)
        if cand is None or cand == w:
            return w
        return cand

    out = token_re.sub(repl, t)
    return out


def _confidence_heuristic(text: str, source: str, duration_seconds: int) -> float:
    if source == SOURCE_FAILED or not (text or "").strip():
        return 8.0
    if _is_mock_transcript(text):
        return 22.0
    wc = len((text or "").split())
    if wc < 4:
        return max(15.0, 28.0 - (4 - wc) * 3)
    base = 52.0 + min(28.0, wc * 0.35)
    if source == SOURCE_GROQ:
        base += 5.0
    if duration_seconds < 5:
        base -= 10.0
    if duration_seconds > 120:
        base -= 5.0
    return float(max(18.0, min(100.0, base)))


def _asr_fallback_whisper_model(primary: str) -> str:
    p = (primary or "").strip().lower()
    if "turbo" in p:
        return "whisper-large-v3"
    return "whisper-large-v3-turbo"


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
    duration_seconds: int,
    question_text: str,
) -> TranscriptionOutcome:
    """
    Transcription **Groq Whisper** avec jusqu’à 3 tentatives (délai + modèle de secours),
    journaux détaillés dans ``attempts_log`` et messages d’échec explicites.
    """
    attempts_log: list[dict[str, Any]] = []
    audio_path = Path(audio_path)
    asr_prompt = _build_verbatim_asr_prompt(question_text)
    orig_abs = str(audio_path.resolve()) if audio_path.is_file() else ""
    orig_size = audio_path.stat().st_size if audio_path.is_file() else 0
    dur_db = int(max(1, min(600, int(duration_seconds or 1))))

    def _cleanup_temp(path: Path, is_temp: bool) -> None:
        if is_temp:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _final_fail(
        marker: str,
        *,
        fail_reason: str,
        raw_before_quality: str | None = None,
        last_exc: str | None = None,
    ) -> TranscriptionOutcome:
        entry = {
            "outcome": "final_failure",
            "fail_reason": fail_reason,
            "marker": marker,
            "raw_transcript_before_fallback_preview": (raw_before_quality or "")[:800],
            "exception": last_exc,
        }
        attempts_log.append(entry)
        print(
            "FINALIZE_ASR_FAILURE",
            {
                "path": orig_abs,
                "size_bytes": orig_size,
                "duration_seconds_db": dur_db,
                "provider": "groq",
                **entry,
            },
            flush=True,
        )
        logger.error(
            "ASR final failure: marker=%s reason=%s raw_preview_len=%s exc=%s",
            marker,
            fail_reason,
            len(raw_before_quality or ""),
            last_exc,
        )
        return TranscriptionOutcome(
            marker,
            SOURCE_FAILED,
            "unknown",
            8.0,
            None,
            None,
            attempts_log=attempts_log,
        )

    def _ok(
        text: str,
        source: str,
        lang: str | None,
        conf: float | None,
        whisper_raw: str | None,
        det: str | None,
    ) -> TranscriptionOutcome:
        t = text or ""
        logger.info(
            "ASR result: transcript_len=%s provider=%s",
            len(t),
            source,
        )
        return TranscriptionOutcome(
            t, source, lang, conf, whisper_raw, det, attempts_log=attempts_log
        )

    if not audio_path.is_file():
        attempts_log.append({"attempt": -1, "error": "input_file_missing", "path": orig_abs})
        return _final_fail(
            TRANSCRIPTION_AUDIO_EMPTY_MARKER,
            fail_reason="input_file_missing",
        )

    path_eff, is_temp = prepare_audio_path_for_asr(audio_path)
    eff_size = path_eff.stat().st_size if path_eff.is_file() else -1
    primary_model = (settings.GROQ_WHISPER_MODEL or "whisper-large-v3-turbo").strip()
    fallback_model = _asr_fallback_whisper_model(primary_model)

    print(
        "FINALIZE_ASR_INPUT",
        {
            "path_original": orig_abs,
            "size_bytes_original": orig_size,
            "path_effective": str(path_eff.resolve()),
            "size_bytes_effective": eff_size,
            "ffmpeg_temp": is_temp,
            "duration_seconds_db": dur_db,
            "provider": "groq",
            "model_primary": primary_model,
            "model_fallback": fallback_model,
        },
        flush=True,
    )
    logger.info(
        "ASR input: path_orig=%s size=%s path_eff=%s size_eff=%s mime=%s ffmpeg_temp=%s duration_s=%s",
        orig_abs,
        orig_size,
        path_eff.resolve(),
        eff_size,
        _mime_for_audio(path_eff),
        is_temp,
        dur_db,
    )

    last_groq_err: str | None = None
    last_exc_str: str | None = None
    last_quality_reason: str | None = None
    last_nonempty_raw: str | None = None

    try:
        print("TRANSCRIPTION START", flush=True)
        for attempt in range(3):
            if attempt > 0:
                time.sleep(0.9)
            model_use = primary_model if attempt < 2 else fallback_model
            model_bind = model_use

            async def _call_one() -> tuple[str | None, str | None, float | None, str | None]:
                return await asyncio.to_thread(
                    transcribe_with_groq,
                    path_eff,
                    settings,
                    None,
                    asr_prompt,
                    model=model_bind,
                )

            attempt_entry: dict[str, Any] = {
                "attempt": attempt,
                "model": model_use,
                "path_effective": str(path_eff.resolve()),
                "size_bytes_effective": eff_size,
                "duration_seconds_db": dur_db,
            }
            try:
                raw, lw, cw, gerr = asyncio.run(asyncio.wait_for(_call_one(), timeout=28))
            except TimeoutError:
                last_groq_err = "groq_timeout"
                last_exc_str = "TimeoutError(>28s)"
                attempt_entry["groq_error"] = last_groq_err
                attempt_entry["exception"] = last_exc_str
                attempts_log.append(attempt_entry)
                print("FINALIZE_ASR_ATTEMPT", attempt_entry, flush=True)
                logger.error("Groq transcription timeout (>28s) attempt=%s", attempt)
                continue
            except Exception as loop_exc:
                last_exc_str = repr(loop_exc)
                last_groq_err = "asyncio_or_wrapper_error"
                attempt_entry["exception"] = last_exc_str
                attempts_log.append(attempt_entry)
                print("FINALIZE_ASR_ATTEMPT", attempt_entry, flush=True)
                logger.exception("ASR attempt wrapper error")
                continue

            attempt_entry["groq_error"] = gerr
            if gerr:
                last_groq_err = gerr
                attempts_log.append(attempt_entry)
                print("FINALIZE_ASR_ATTEMPT", attempt_entry, flush=True)
                logger.error("Groq ASR attempt failed: %s", gerr)
                continue

            raw_preview = (raw or "").strip()
            attempt_entry["raw_transcript_returned_preview"] = raw_preview[:500]
            attempt_entry["raw_transcript_len"] = len(raw_preview)

            if not raw_preview:
                last_groq_err = "groq_empty_text_response"
                attempts_log.append(attempt_entry)
                print("FINALIZE_ASR_ATTEMPT", attempt_entry, flush=True)
                logger.error("Groq returned empty text attempt=%s", attempt)
                continue

            last_nonempty_raw = raw_preview
            last_groq_err = None
            last_exc_str = None
            ok_q, qreason = validate_transcript_quality(raw_preview, dur_db)
            attempt_entry["quality_ok"] = ok_q
            attempt_entry["quality_reason"] = qreason
            if not ok_q and raw_preview.strip():
                # Dernière sécurité : ne pas remplacer un transcript Whisper réel par un marqueur d’échec.
                attempt_entry["quality_relaxed_accept_nonempty"] = True
                attempt_entry["quality_would_reject_reason"] = qreason
                ok_q = True
                qreason = f"{qreason}|accepted_nonempty_whisper_raw"
                attempt_entry["quality_ok"] = True
                attempt_entry["quality_reason"] = qreason
                logger.warning(
                    "ASR: qualité rejetée mais transcript non vide conservé (%s)",
                    attempt_entry.get("quality_would_reject_reason"),
                )
            if not ok_q:
                last_quality_reason = qreason
                attempts_log.append(attempt_entry)
                print("FINALIZE_ASR_ATTEMPT", attempt_entry, flush=True)
                logger.warning(
                    "Transcript quality rejected (attempt=%s): %s raw_len=%s raw_preview=%r",
                    attempt,
                    qreason,
                    len(raw_preview),
                    raw_preview[:300],
                )
                continue

            det = detect_transcript_language(raw_preview, question_text)
            lang = _finalize_stored_language(raw_preview, lw, question_text)
            conf = cw if cw is not None else _confidence_heuristic(
                raw_preview, SOURCE_GROQ, dur_db
            )
            attempts_log.append({**attempt_entry, "outcome": "success"})
            print("FINALIZE_ASR_ATTEMPT", {**attempt_entry, "outcome": "success"}, flush=True)
            logger.info("Transcript language detected: %s", det)
            logger.info("Transcript quality: passed (%s)", qreason)
            logger.info("Groq transcription success model=%s", model_use)
            print("TRANSCRIPTION DONE", flush=True)
            return _ok(raw_preview, SOURCE_GROQ, lang, conf, lw, det)

        print("TRANSCRIPTION DONE", flush=True)

        if orig_size == 0:
            return _final_fail(
                TRANSCRIPTION_AUDIO_EMPTY_MARKER,
                fail_reason="zero_byte_file",
            )
        if orig_size < ASR_VERY_SMALL_BYTES_WARN and not last_nonempty_raw:
            return _final_fail(
                TRANSCRIPTION_AUDIO_EMPTY_MARKER,
                fail_reason=f"very_small_file_bytes={orig_size}",
            )
        if last_nonempty_raw and last_quality_reason:
            return _final_fail(
                f"{TRANSCRIPTION_AUDIO_UNCLEAR_MARKER} (quality:{last_quality_reason})",
                fail_reason=f"quality_rejected:{last_quality_reason}",
                raw_before_quality=last_nonempty_raw,
            )
        if last_groq_err == "groq_empty_text_response" and orig_size > 0:
            return _final_fail(
                TRANSCRIPTION_AUDIO_UNCLEAR_MARKER,
                fail_reason="groq_empty_text_audio_present",
            )
        provider_classified = bool(last_exc_str) or (
            last_groq_err
            and (
                last_groq_err == "groq_timeout"
                or last_groq_err.startswith("groq_exception:")
                or last_groq_err == "asyncio_or_wrapper_error"
                or last_groq_err
                in (
                    "groq_api_key_missing",
                    "audio_file_not_found",
                    "os_read_error",
                    "empty_file_bytes",
                )
            )
        )
        if provider_classified:
            return _final_fail(
                TRANSCRIPTION_PROVIDER_ERROR_MARKER,
                fail_reason=last_groq_err or "provider_error",
                raw_before_quality=last_nonempty_raw,
                last_exc=last_exc_str or last_groq_err,
            )
        if last_nonempty_raw:
            return _final_fail(
                TRANSCRIPTION_AUDIO_UNCLEAR_MARKER,
                fail_reason="unknown_after_retries",
                raw_before_quality=last_nonempty_raw,
            )
        if orig_size > 0:
            return _final_fail(
                TRANSCRIPTION_AUDIO_UNCLEAR_MARKER,
                fail_reason="empty_transcript_audio_present",
            )
        return _final_fail(
            TRANSCRIPTION_AUDIO_EMPTY_MARKER,
            fail_reason="no_usable_audio",
        )
    finally:
        _cleanup_temp(path_eff, is_temp)


def _stored_to_clean_lang(stored: str | None) -> str | None:
    if not stored:
        return None
    s = str(stored).lower().strip()
    if s == "ar_darija":
        return "darija"
    if s == "ar_msa":
        return "ar"
    if s in ("fr", "en"):
        return s
    return None


def _clean_arabic_script_surface(t: str) -> str:
    # Tatweel répété / inutile
    t = re.sub(r"\u0640+", "", t)
    # Espaces autour des signes arabes de ponctuation courants
    t = re.sub(r"\s*([؟،؛])\s*", r" \1 ", t)
    t = re.sub(r" {2,}", " ", t)
    return t


def _clean_latin_surface(t: str, lang: str) -> str:
    # Espace avant ponctuation finale (artefact ASR)
    t = re.sub(r"\s+([.,!?;:…])", r"\1", t)
    if lang == "fr":
        t = re.sub(r" ([?!:;%])", r"\1", t)
        t = re.sub(r"\s+(»)", r"\1", t)
        t = re.sub(r"(«)\s+", r"\1", t)
    if lang == "en":
        t = re.sub(r"\s+([,;:!?])", r"\1", t)
    t = re.sub(r" {2,}", " ", t)
    return t


def _polish_latin_transcript_fr_en(text: str, lang: str) -> str:
    """
    Typographie légère FR/EN après ASR : apostrophes typographiques, élisions espacées, ponctuation.
    Ne reformule pas et n’ajoute pas de mots.
    """
    t = (text or "").strip()
    if not t or lang not in ("fr", "en"):
        return t
    t = unicodedata.normalize("NFC", t)
    for u in ("\u2018", "\u2019", "\u0060", "\u00b4", "\u2032"):
        t = t.replace(u, "'")
    if lang == "en":
        for u in ("\u201c", "\u201d"):
            t = t.replace(u, '"')
    t = re.sub(r"(\w)\s+'\s*(\w)", r"\1'\2", t)
    t = re.sub(r" {2,}", " ", t)
    t = _clean_latin_surface(t, lang)
    return t.strip()


def _normalize_transcript_unicode_minimal(raw: str) -> str:
    """
    Post-traitement **minimal** du texte ASR : espaces, BOM, NFC pour scripts arabes.
    Ne traduit pas ; ne supprime pas les signes de formatage (U+200C/U+200D) ni l’arabe.
    """
    t = (raw or "").strip()
    if not t:
        return t
    if t.startswith("```"):
        t = re.sub(r"^```(?:\w*)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()
    t = t.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    t = t.replace("\ufeff", "")
    t = re.sub(r"[\t\r\n]+", " ", t)
    t = re.sub(r" {2,}", " ", t)
    if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", t):
        t = unicodedata.normalize("NFC", t)
    return t.strip()


def clean_transcript(raw: str, language: str | None = None) -> str:
    """
    Post-traitement ASR étendu (ponctuation, tatweel, etc.). Pour le flux oral principal,
    utiliser `_normalize_transcript_unicode_minimal` pour garder le texte modèle.
    `language` : fr | en | ar | darija | None (détection auto pour les règles spécifiques).
    Ne reformule pas le fond ni ne traduit.
    """
    t = (raw or "").strip()
    if not t:
        return t
    if t.startswith("```"):
        t = re.sub(r"^```(?:\w*)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()
    t = t.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    t = t.replace("\ufeff", "").replace("\u200b", "")
    t = re.sub(r"[\t\r\n]+", " ", t)
    t = re.sub(r" {2,}", " ", t)

    lang = (language or "").strip().lower()
    if not lang or lang == "unknown":
        lang = detect_transcript_language(t)

    if re.search(r"[\u0600-\u06FF]", t):
        t = unicodedata.normalize("NFC", t)
        t = _clean_arabic_script_surface(t)

    if lang in ("fr", "en"):
        t = _clean_latin_surface(t, lang)
    elif lang == "darija":
        # Latin + arabe mélangés : ponctuation latine + espaces arabes
        t = _clean_latin_surface(t, "fr")
        if re.search(r"[\u0600-\u06FF]", t):
            t = _clean_arabic_script_surface(t)
    elif lang == "ar":
        pass

    t = re.sub(r" {2,}", " ", t)
    return t.strip()


def _normalize_similarity_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\W_]+", " ", s, flags=re.UNICODE)
    return re.sub(r" {2,}", " ", s).strip()


def _char_ngram_set(s: str, n: int) -> set[str]:
    s = re.sub(r"\s+", "", _normalize_similarity_text(s))
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


def similarity_question_answer(question_text: str, transcript: str) -> float:
    """
    Similarité question ↔ réponse (0–1), multilingue : séquences, tokens, n-grammes caractères.
    Pas de traduction : compare les surfaces textuelles alignées.
    """
    if _is_mock_transcript(transcript):
        return 0.11
    qn = _normalize_similarity_text(question_text)
    tn = _normalize_similarity_text(transcript)
    if len(tn) < 2:
        return 0.0
    if len(qn) < 2:
        return min(1.0, max(0.0, len(tn) / 160.0))

    seq_ratio = SequenceMatcher(None, qn, tn).ratio()

    wq = _tokenize_multilingual(question_text)
    wt = _tokenize_multilingual(transcript)
    w_union = wq | wt
    w_j = len(wq & wt) / len(w_union) if w_union else 0.0

    bq2 = _char_ngram_set(qn, 2)
    bt2 = _char_ngram_set(tn, 2)
    b_j2 = _jaccard(bq2, bt2)

    bq3 = _char_ngram_set(qn, 3)
    bt3 = _char_ngram_set(tn, 3)
    b_j3 = _jaccard(bq3, bt3) if (bq3 or bt3) else b_j2

    combined = 0.22 * seq_ratio + 0.28 * w_j + 0.28 * b_j2 + 0.22 * b_j3
    return float(max(0.0, min(1.0, combined)))


def repetition_intensity(transcript: str) -> float:
    """0–100 : répétitions de mots / boucles (indicateur d’hésitation)."""
    words = re.findall(
        r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+",
        (transcript or "").lower(),
    )
    if len(words) < 5:
        return 0.0
    c = Counter(words)
    total = len(words)
    uniq_ratio = len(c) / total
    rep_ratio = max(0.0, 1.0 - uniq_ratio)
    burst = sum(max(0, n - 1) for n in c.values()) / max(total, 1)
    return float(max(0.0, min(100.0, rep_ratio * 62.0 + burst * 38.0)))


def detect_repetitive_answer(transcript: str) -> dict[str, Any]:
    """
    Détection déterministe de réponses pauvres/répétitives (production) :
    - « je sais pas » en boucle
    - fillers répétés (euh/eeeeh/…)
    - très faible diversité lexicale
    Retourne un score 0–100 (100 = très répétitif) + flags.
    """
    t = (transcript or "").strip().lower()
    if not t:
        return {"repetition_score": 0.0, "flags": [], "jspp_count": 0, "filler_count": 0}

    jspp = len(re.findall(r"\bje\s+ne\s+sais\s+pas\b|\bje\s+sais\s+pas\b", t))
    fillers = len(FILLER_RE.findall(t)) + len(re.findall(r"\b(e+u+h+|e{3,}h+|h+e+u+)\b", t))
    words = re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I)
    uniq_ratio = (len(set(words)) / max(len(words), 1)) if words else 1.0

    flags: list[str] = []
    if jspp >= 2:
        flags.append("je_sais_pas_repeated")
    if fillers >= 4:
        flags.append("many_fillers")
    if len(words) >= 8 and uniq_ratio < 0.38:
        flags.append("low_lexical_diversity")

    score = 0.0
    score += min(70.0, jspp * 28.0)
    score += min(35.0, fillers * 4.5)
    score += max(0.0, (0.55 - uniq_ratio) * 85.0) if len(words) >= 8 else 0.0
    score = float(max(0.0, min(100.0, score)))

    return {
        "repetition_score": round(score, 2),
        "flags": flags,
        "jspp_count": jspp,
        "filler_count": fillers,
        "unique_ratio": round(uniq_ratio, 3) if words else None,
    }


def pause_marker_intensity(transcript: str) -> float:
    """0–100 : marqueurs de pauses / blancs dans le texte ASR."""
    t = transcript or ""
    dots = len(re.findall(r"\.{2,}|…", t))
    comm = len(re.findall(r",\s*,", t))
    punct_pause = len(re.findall(r"[;:]\s{2,}", t))
    dash = len(re.findall(r"—|–", t))
    score = dots * 13.0 + comm * 11.0 + punct_pause * 9.0 + dash * 7.0
    return float(min(100.0, score))


def hesitation_score_from_duration(duration_seconds: int) -> float:
    d = max(1, min(duration_seconds, 600))
    if d <= 8:
        return min(100.0, 35.0 + (8 - d) * 3.0)
    if d <= 90:
        return min(100.0, 25.0 + d * 0.45)
    return min(100.0, 55.0 + (d - 90) * 0.15)


def hesitation_score_combined(duration_seconds: int, transcript: str) -> float:
    """
    Hésitation : durée + fillers + marqueurs de pause dans le transcript + répétitions.
    """
    base_dur = hesitation_score_from_duration(duration_seconds)
    t = transcript or ""
    rep_meta = detect_repetitive_answer(t)
    fillers = len(FILLER_RE.findall(t)) + len(HESITATION_MARKERS.findall(t))
    wc = max(1, len(t.split()))
    filler_block = min(
        42.0,
        fillers * 3.6 + (fillers / max(wc / 22.0, 1.0)) * 5.5,
    )
    # Boost si fillers / boucles détectées (retour terrain)
    filler_block += min(18.0, float(rep_meta.get("filler_count") or 0) * 2.1)
    pause_like = len(re.findall(r"\.{2,}|…", t)) + len(re.findall(r",\s{0,3},", t))
    pause_block = min(28.0, pause_like * 5.2)
    rep = repetition_intensity(t) * 0.34
    rep += float(rep_meta.get("repetition_score") or 0.0) * 0.18
    pause_txt = pause_marker_intensity(t) * 0.26
    text_h = filler_block * 0.38 + pause_block * 0.18 + rep + pause_txt
    return float(max(0.0, min(100.0, base_dur * 0.44 + text_h * 0.56)))


def _tokenize_multilingual(text: str) -> set[str]:
    text = (text or "").lower()
    latin = set(re.findall(r"[a-zàâäéèêëïîôùûç0-9]{3,}", text))
    arabic = set(re.findall(r"[\u0600-\u06FF]{2,}", text))
    return latin | arabic


def _has_arabic_script(s: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", s or ""))


# Stopwords (FR/EN) — pour extraire des termes « domaine » de la question
_RELEVANCE_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "he",
        "she",
        "his",
        "her",
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "et",
        "ou",
        "mais",
        "dans",
        "sur",
        "sous",
        "pour",
        "par",
        "avec",
        "sans",
        "chez",
        "entre",
        "est",
        "sont",
        "été",
        "être",
        "avoir",
        "ai",
        "as",
        "a",
        "avez",
        "ont",
        "ce",
        "cet",
        "cette",
        "ces",
        "cela",
        "ça",
        "qui",
        "que",
        "quoi",
        "dont",
        "où",
        "comme",
        "très",
        "plus",
        "moins",
        "pas",
        "ne",
        "n",
        "y",
        "en",
        "lui",
        "leur",
        "vos",
        "nos",
        "mes",
        "tes",
        "ses",
        "mon",
        "ton",
        "son",
        "notre",
        "votre",
        "quel",
        "quels",
        "quelle",
        "quelles",
    }
)

# Réponses purement génériques / présentation sans lien avec le fond de la question
_GENERIC_ANSWER_RE = re.compile(
    r"(?is)"
    r"\b(je\s+m['’]appelle|mon\s+nom\s+est|j['’]habite|je\s+viens\s+de|je\s+suis\s+né|"
    r"je\s+suis\s+étudiant|j['’]ai\s+\d+\s+ans|"
    r"my\s+name\s+is|i\s+am\s+from|i['’]m\s+from|i\s+live\s+in|i\s+am\s+a\s+student|"
    r"اسمي|أنا\s+من|من\s+مدينة)\b"
)

_RELEVANCE_LLM_MAX_CHARS = 2800


def _strip_accents_lower(s: str) -> str:
    """Normalise pour matcher des consignes FR/EN (présentez / presentez)."""
    nfd = unicodedata.normalize("NFD", (s or "").strip())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


def _is_intro_question(question_text: str) -> bool:
    """
    Questions dont la réponse attendue est une présentation / parcours personnel.
    """
    raw = (question_text or "").strip()
    if not raw:
        return False
    q = _strip_accents_lower(raw)
    q = re.sub(r"\s+", " ", q).strip()
    patterns = (
        r"presentez[- ]?vous",
        r"presente[- ]?toi",
        r"parlez[- ]?moi de vous",
        r"parlez[- ]?moi de votre parcours",
        r"parlez de vous",
        r"parlez[- ]?nous de vous",
        r"dites[- ]?moi qui vous etes",
        r"qui etes[- ]?vous",
        r"qui etes vous",
        r"tell me about yourself",
        r"introduce yourself",
        r"could you introduce yourself",
        r"describe your(?:self| background)",
        r"describe yourself",
        r"who are you",
        r"talk about yourself",
        r"your background",
        r"une presentation de vous",
        r"votre presentation",
        r"presentez votre parcours",
        r"faites votre presentation",
    )
    return any(re.search(p, q, re.I) for p in patterns)


def _intro_answer_signal_count(transcript: str) -> int:
    """Indices de contenu attendu pour une auto-présentation (nom, âge, lieu, formation, pro)."""
    t = (transcript or "").strip().lower()
    n = 0
    if re.search(
        r"je\s+m['']appelle|mon\s+nom\s+est|my\s+name\s+is|i\s*'?\s*m\b|je\s+suis\s+\w+",
        t,
        re.I,
    ):
        n += 1
    if re.search(r"\b\d{1,2}\s*(ans|years?|yo)\b", t, re.I):
        n += 1
    if re.search(
        r"j['']habite|je\s+viens\s+de|je\s+suis\s+de|i\s*'?\s*m\s+from|i\s+live\s+in|"
        r"habite\s+a|j['']ai\s+grandi|résid",
        t,
        re.I,
    ):
        n += 1
    if re.search(
        r"dipl[oô]me|master|licence|doctorat|universit|étudiant|student|formation|degree|école",
        t,
        re.I,
    ):
        n += 1
    if re.search(
        r"expérience|parcours|carrière|travaill|poste|entreprise|professionnel|experience|worked|career|emploi",
        t,
        re.I,
    ):
        n += 1
    return min(n, 6)


def _relevance_score_intro_answer(transcript: str) -> float:
    """
    Score 45–100 pour une réponse à une question de type « présentez-vous ».
    Faible : peu de signaux ; fort : plusieurs signaux + un minimum de matière.
    """
    t = (transcript or "").strip()
    words = re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I)
    wc = len(words)
    n = _intro_answer_signal_count(t)
    if n == 0:
        base = 46.0 + min(8.0, wc * 0.4)
    elif n == 1:
        base = 52.0 + min(10.0, wc * 0.25)
    elif n == 2:
        base = 64.0 + min(8.0, wc * 0.2)
    elif n == 3:
        base = 72.0 + min(8.0, wc * 0.18)
    else:
        base = 82.0 + min(14.0, (n - 3) * 4.0 + wc * 0.12)
    return float(max(45.0, min(100.0, base)))


def _question_domain_keywords(question_text: str) -> set[str]:
    """Verbes et termes de domaine (hors stopwords), tokens multilingues."""
    raw = _tokenize_multilingual(question_text)
    out: set[str] = set()
    for w in raw:
        wl = w.lower() if re.match(r"^[a-zàâäéèêëïîôùûç0-9]+$", w, re.I) else w
        if re.match(r"^[\u0600-\u06FF]+$", w):
            if len(w) >= 2:
                out.add(w)
            continue
        if len(w) < 3 and not w.isdigit():
            continue
        if wl in _RELEVANCE_STOPWORDS:
            continue
        out.add(wl)
    return out


def _keyword_overlap_ratio(question_keywords: set[str], transcript: str) -> float:
    if not question_keywords:
        return 0.0
    tt = _tokenize_multilingual(transcript)
    if not tt:
        return 0.0
    inter = 0
    for qk in question_keywords:
        if qk in tt:
            inter += 1
            continue
        if re.match(r"^[a-zàâäéèêëïîôùûç0-9]+$", qk, re.I):
            qlow = qk.lower()
            if any(
                (re.match(r"^[a-zàâäéèêëïîôùûç0-9]+$", x, re.I) and x.lower() == qlow)
                for x in tt
            ):
                inter += 1
    return float(inter / max(len(question_keywords), 1))


def _is_generic_intro_only(transcript: str, question_keywords: set[str]) -> bool:
    t = (transcript or "").strip()
    if len(t) < 10:
        return False
    if not _GENERIC_ANSWER_RE.search(t):
        return False
    ov = _keyword_overlap_ratio(question_keywords, t)
    return ov < 0.08


def _score_hard_gate_near_zero(kw: float, sim: float) -> float:
    """Score forcé 0–10 (hors sujet évident / générique). Déterministe pour faciliter le debug."""
    base = 0.8 + sim * 5.5 + kw * 35.0
    return float(max(0.0, min(10.0, base)))


def _hard_gate_obvious_off_topic(
    question_keywords: set[str],
    kw_overlap: float,
    sim: float,
) -> bool:
    """
    True si la réponse n’a pratiquement aucun lien surface avec la question :
    le LLM ne doit pas être appelé (pas de remontée de score par synonymes).
    """
    n = len(question_keywords)
    if n >= 2:
        return kw_overlap < 0.04 and sim < 0.15
    if n == 1:
        return kw_overlap < 0.02 and sim < 0.12
    return False


def _heuristic_relevance_banded(question_text: str, transcript: str) -> float:
    """
    Sans LLM : score strict par bandes à partir de similarité surface + chevauchement mots-clés.
    """
    sim = similarity_question_answer(question_text, transcript)
    qkw = _question_domain_keywords(question_text)
    kw = _keyword_overlap_ratio(qkw, transcript)
    combined = 0.32 * sim + 0.68 * kw
    if len(qkw) >= 2 and kw < 0.02 and sim < 0.11:
        combined = min(combined, 0.09)
    if combined < 0.16:
        return float(max(0.0, min(20.0, 3.0 + combined * 95.0)))
    if combined < 0.42:
        return float(30.0 + (combined - 0.16) / 0.26 * 30.0)
    return float(min(100.0, 70.0 + (combined - 0.42) / 0.58 * 30.0))


def _groq_relevance_score_llm(
    question_text: str,
    transcript: str,
    settings: Settings,
    *,
    intro_question: bool = False,
) -> float | None:
    api_key = (settings.GROQ_API_KEY or "").strip()
    if not api_key:
        return None
    model = (settings.GROQ_MODEL or "llama-3.3-70b-versatile").strip()
    q = (question_text or "").strip()[:_RELEVANCE_LLM_MAX_CHARS]
    a = (transcript or "").strip()[:_RELEVANCE_LLM_MAX_CHARS]
    if len(q) < 4 or len(a) < 4:
        return None
    if intro_question:
        prompt = (
            "You evaluate a self-introduction answer to an interview question asking the candidate "
            "to present themselves (background, identity, path).\n\n"
            f"Question:\n{q}\n\n"
            f"Answer:\n{a}\n\n"
            "Score how appropriate and complete the self-introduction is.\n\n"
            "Rules:\n"
            "- Weak or very thin intro → 45–55\n"
            "- Decent intro (some identity/background elements) → 55–75\n"
            "- Strong intro (clear identity + useful detail) → 75–95\n"
            "- Exceptional richness and clarity → up to 100\n\n"
            "Return ONLY a number from 0 to 100, no other text."
        )
    else:
        prompt = (
            "You are evaluating an interview answer.\n"
            "Surface checks already established that the answer is plausibly on-topic.\n\n"
            f"Question:\n{q}\n\n"
            f"Answer:\n{a}\n\n"
            "Score how well the answer addresses the question (depth and fit).\n\n"
            "Rules:\n"
            "- Weak but on-topic → 21–35\n"
            "- Partially addresses the question → 30–60\n"
            "- Clearly answers with substance → 70–100\n\n"
            "Return ONLY a number from 0 to 100, no other text."
        )
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        print("AI ANALYSIS START", flush=True)

        async def _call() -> Any:
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                temperature=0.1,
                max_tokens=16,
                messages=[
                    {
                        "role": "system",
                        "content": "You output only an integer from 0 to 100.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )

        try:
            completion = asyncio.run(asyncio.wait_for(_call(), timeout=20))
        except TimeoutError:
            logger.warning("relevance LLM timeout (>20s)")
            return None
        finally:
            print("AI ANALYSIS DONE", flush=True)
        raw = (completion.choices[0].message.content or "").strip()
        m = re.search(r"-?\d+(?:[.,]\d+)?", raw)
        if not m:
            logger.warning("relevance LLM: no number in response")
            return None
        val = float(m.group(0).replace(",", "."))
        return float(max(0.0, min(100.0, val)))
    except Exception as exc:
        logger.warning("relevance LLM (Groq) indisponible — %s", exc)
        return None


def relevance_score_from_text(
    transcript: str,
    question_text: str,
    *,
    use_llm: bool = True,
) -> float:
    transcript = (transcript or "").strip()
    settings = get_settings()
    score: float
    if len(transcript) < 8:
        score = float(max(4.0, min(28.0, 4.0 + len(transcript) * 1.2)))
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_mode": "intro_question"
                if _is_intro_question(question_text)
                else "strict_non_intro",
            },
        )
        return score
    if _is_mock_transcript(transcript):
        q_tokens = _tokenize_multilingual(question_text)
        if not q_tokens:
            score = 22.0
        else:
            score = float(18.0 + min(12.0, len(q_tokens) * 0.6))
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_mode": "intro_question"
                if _is_intro_question(question_text)
                else "strict_non_intro",
            },
        )
        return score

    qkw = _question_domain_keywords(question_text)
    kw = _keyword_overlap_ratio(qkw, transcript)
    sim = similarity_question_answer(question_text, transcript)

    # --- Détection répétition / réponse vide ---
    rep_meta = detect_repetitive_answer(transcript)
    rep_score = float(rep_meta.get("repetition_score") or 0.0)
    jspp = int(rep_meta.get("jspp_count") or 0)

    # --- Règles métier (retour terrain) : Q2/Q3 et réponses « je sais pas » ---
    qn = _strip_accents_lower(question_text or "")
    tn = _strip_accents_lower(transcript)

    def _has_any(token_list: list[str]) -> bool:
        return any(tok in tn for tok in token_list)

    # Q2 parcours / expérience : si aucun mot-clé, cap bas.
    if any(k in qn for k in ("parcours", "experience", "expérience", "stage", "travail", "diplome", "diplôme", "projet")):
        if not _has_any(["parcours", "experience", "expérience", "stage", "travail", "diplome", "diplôme", "projet", "mission", "poste", "entreprise", "ecole", "école", "formation"]):
            score = 25.0
            print(
                "ANSWER QUALITY DEBUG:",
                {"question": (question_text or "")[:120], "cap": "q2_keywords_missing", "relevance_score": score},
                flush=True,
            )
            return score

    # Q3 motivation : si aucun mot-clé, cap bas.
    if any(k in qn for k in ("pourquoi", "postul", "motivation", "candid")):
        if not _has_any(["motivation", "poste", "entreprise", "competence", "compétence", "interet", "intérêt", "mission", "valeur", "projet"]):
            score = 30.0
            print(
                "ANSWER QUALITY DEBUG:",
                {"question": (question_text or "")[:120], "cap": "q3_keywords_missing", "relevance_score": score},
                flush=True,
            )
            return score

    # « je sais pas » répété : relevance max 20 (hors intro).
    if jspp >= 2 and not _is_intro_question(question_text):
        score = 20.0
        print(
            "ANSWER QUALITY DEBUG:",
            {
                "question": (question_text or "")[:120],
                "cap": "je_sais_pas_repeated",
                "jspp_count": jspp,
                "repetition_score": rep_score,
                "relevance_score": score,
            },
            flush=True,
        )
        return score

    # Question « présentez-vous » : ne pas appliquer le filtre « intro générique = hors-sujet »
    if _is_intro_question(question_text):
        h = _relevance_score_intro_answer(transcript)
        llm_score = (
            _groq_relevance_score_llm(
                question_text,
                transcript,
                settings,
                intro_question=True,
            )
            if use_llm
            else None
        )
        if llm_score is not None:
            blended = 0.68 * h + 0.32 * float(llm_score)
            # Ne pas faire chuter le score en dessous d’une fraction de l’heuristique (LLM parfois trop dur)
            score = float(max(45.0, min(100.0, max(blended, h * 0.92))))
            rel_src = "intro_heuristic_llm_blend"
        else:
            score = h
            rel_src = "intro_heuristic"
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_mode": "intro_question",
                "relevance_source": rel_src,
            },
        )
        return score

    # --- Hard gate (mode strict, questions non-intro) ---
    if _is_generic_intro_only(transcript, qkw):
        score = _score_hard_gate_near_zero(kw, sim)
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_gate": "generic_intro",
                "relevance_source": "hard_gate",
                "relevance_mode": "strict_non_intro",
            },
        )
        return score

    if _hard_gate_obvious_off_topic(qkw, kw, sim):
        score = _score_hard_gate_near_zero(kw, sim)
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_gate": "obvious_off_topic",
                "relevance_source": "hard_gate",
                "relevance_mode": "strict_non_intro",
                "kw_overlap": round(kw, 4),
                "sim": round(sim, 4),
            },
        )
        return score

    llm_score = (
        _groq_relevance_score_llm(question_text, transcript, settings, intro_question=False)
        if use_llm
        else None
    )
    if llm_score is not None:
        score = float(llm_score)
        # Post-cap : évite un 80+ sur réponse très répétitive / pauvre
        if rep_score >= 65 and not _is_intro_question(question_text):
            score = min(score, 35.0)
        logger.info(
            "Relevance check",
            extra={
                "question": (question_text or "")[:100],
                "answer": transcript[:100],
                "score": score,
                "relevance_source": "groq_llm",
                "relevance_mode": "strict_non_intro",
            },
        )
        print(
            "ANSWER QUALITY DEBUG:",
            {
                "question": (question_text or "")[:120],
                "repetition_score": rep_score,
                "relevance_score": round(score, 2),
                "hesitation_score_hint": round(hesitation_score_combined(25, transcript), 2),
            },
            flush=True,
        )
        return score

    score = _heuristic_relevance_banded(question_text, transcript)
    if rep_score >= 65 and not _is_intro_question(question_text):
        score = min(score, 35.0)
    logger.info(
        "Relevance check",
        extra={
            "question": (question_text or "")[:100],
            "answer": transcript[:100],
            "score": score,
            "relevance_source": "heuristic",
            "relevance_mode": "strict_non_intro",
        },
    )
    print(
        "ANSWER QUALITY DEBUG:",
        {
            "question": (question_text or "")[:120],
            "repetition_score": rep_score,
            "relevance_score": round(score, 2),
        },
        flush=True,
    )
    return score


def compute_text_coherence_score(transcript: str) -> float:
    """
    Score 0–100 : cohérence textuelle heuristique (ponctuation, diversité lexicale,
    bruit symbole, répétitions extrêmes, morceaux sans structure de phrase).
    """
    t = (transcript or "").strip()
    if len(t) < 10:
        return 0.0
    if re.search(r"(.)\1{7,}", t):
        return 8.0
    letters = len(re.findall(r"[\wàâäéèêëïîôùûç]", t, re.I))
    alnum_ratio = letters / max(len(t), 1)
    if alnum_ratio < 0.34:
        return float(max(0.0, min(28.0, alnum_ratio * 75.0)))
    non_wordish = len(
        re.findall(
            r"[^\w\sàâäéèêëïîôùûç.,;:!?…'\"«»()\[\]{}—–\-]",
            t,
        )
    )
    noise = non_wordish / max(len(t), 1)
    if noise > 0.24:
        return float(max(5.0, min(32.0, 55.0 - noise * 140.0)))

    words = re.findall(r"[\wàâäéèêëïîôùûç'-]{2,}|[\u0600-\u06FF]+", t, re.I)
    wc = len(words)
    if wc < 2:
        return max(10.0, min(38.0, len(t) * 0.45))

    counts = Counter(w.lower() for w in words)
    top_freq = counts.most_common(1)[0][1]
    if wc >= 6 and top_freq / wc >= 0.52:
        return max(6.0, 24.0)

    short_frac = sum(1 for w in words if len(w) <= 2) / wc
    if wc >= 10 and short_frac > 0.58:
        return max(8.0, 30.0)

    if re.search(r"[@#$%^&*_=]{4,}", t) and noise > 0.08:
        return min(35.0, 22.0)

    lat = sum(
        1
        for c in t
        if (c.isascii() and c.isalpha() and "a" <= c.lower() <= "z")
        or c in "àâäéèêëïîôùûçÀÂÄÉÈÊËÏÎÔÙÛ"
    )
    arb = sum(1 for c in t if "\u0600" <= c <= "\u06FF")
    mixed_penalty = 0.0
    if lat > 30 and arb > 30:
        r_small = min(lat, arb) / max(lat, arb)
        if r_small > 0.38:
            mixed_penalty = 18.0

    sents = [s.strip() for s in re.split(r"(?<=[.!?…\u061F])\s+", t) if s.strip()]
    struct_bonus = 10.0 if len(sents) >= 2 else (6.0 if len(t) < 85 else 0.0)
    if len(t) > 100 and len(sents) <= 1 and not re.search(r"[.!?…]\s*$", t.rstrip()):
        struct_bonus -= 14.0

    uniq_ratio = len(set(w.lower() for w in words)) / wc
    vowel_pat = re.compile(r"[aeiouyàâäéèêëïîôùûAEIOUYÀÂÄÉÈÊËÏÎÔÙÛ]", re.I)
    cons_runs = re.findall(r"[bcdfghjklmnpqrstvwxzBCDFGHJKLMNPQRSTVWXZ]{6,}", t)
    cons_penalty = min(22.0, len(cons_runs) * 11.0)
    vowelish = sum(1 for w in words if vowel_pat.search(w))
    vow_ratio = vowelish / max(wc, 1)
    if wc >= 8 and vow_ratio < 0.35:
        cons_penalty += 12.0

    base = 30.0 + uniq_ratio * 48.0 + struct_bonus + min(alnum_ratio * 28.0, 22.0)
    score = base - mixed_penalty - cons_penalty
    return float(max(0.0, min(100.0, score)))


def is_incoherent_gibberish_transcript(
    transcript: str,
    coherence: float,
    relevance: float,
) -> bool:
    """
    Règle dure : texte incohérent / charabia → qualité « faible » indépendamment des autres scores.
    """
    t = (transcript or "").strip()
    if len(t) < 12:
        return True
    if coherence <= 18.0:
        return True
    if re.search(r"(.)\1{8,}", t):
        return True
    letters = len(re.findall(r"[\wàâäéèêëïîôùûç]", t, re.I))
    if letters / max(len(t), 1) < 0.30:
        return True
    if relevance < 30.0 and coherence < 45.0:
        return True
    if re.search(
        r"\b(asdf|qwerty|qazwsx|zxcv|hjkl|wxyz|testtest|lorem ipsum)\b",
        t,
        re.I,
    ):
        return True
    words = re.findall(r"[\wàâäéèêëïîôùûç'-]{2,}", t, re.I)
    if len(words) >= 14:
        short = sum(1 for w in words if len(w) <= 2)
        if short / len(words) > 0.65:
            return True
    return False


def clarity_score_from_text(transcript: str) -> float:
    t = (transcript or "").strip()
    if len(t) < 15:
        return max(8.0, min(45.0, len(t) * 2.2))
    words = re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I)
    if not words:
        return 25.0
    wc = len(words)
    uniq = len(set(w.lower() for w in words))
    ratio = uniq / max(wc, 1)
    rep_penalty = max(0.0, (1.0 - ratio) * 55.0)
    fillers = len(FILLER_RE.findall(t))
    filler_penalty = min(35.0, fillers * 5.5)
    sents = re.split(r"(?<=[.!?…\u061F])\s+", t)
    sents = [s for s in sents if s.strip()]
    if not sents:
        sents = [t]
    lens = [len(x.split()) for x in sents]
    avg_len = sum(lens) / max(len(lens), 1)
    if avg_len < 4:
        len_score = 35.0
    elif avg_len <= 38:
        len_score = 72.0
    else:
        len_score = max(40.0, 78.0 - (avg_len - 38) * 0.8)
    score = len_score + ratio * 22.0 - rep_penalty - filler_penalty
    return float(max(5.0, min(100.0, score)))


def language_quality_score_from_text(transcript: str) -> float:
    t = (transcript or "").strip()
    if len(t) < 12:
        return max(10.0, min(40.0, len(t) * 1.8))
    words = re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I)
    if not words:
        return 22.0
    wc = len(words)
    uniq = len(set(w.lower() for w in words))
    diversity = uniq / max(wc, 1)
    char_per_word = len(t) / max(wc, 1)
    balance = 1.0 - abs(math.log(max(char_per_word, 2.5)) - math.log(5.2)) / 3.0
    balance = max(0.0, min(1.0, balance))
    score = 32.0 + diversity * 48.0 + balance * 22.0
    if re.search(r"[!?]{4,}", t):
        score -= 12.0
    return float(max(8.0, min(100.0, score)))


def answer_confidence_score_from_signals(
    hesitation: float,
    transcript: str,
) -> float:
    t = transcript or ""
    base = max(0.0, min(100.0, 100.0 - hesitation * 0.62))
    fillers = len(FILLER_RE.findall(t))
    base -= min(28.0, fillers * 4.0)
    hes_mark = len(HESITATION_MARKERS.findall(t))
    base -= min(22.0, hes_mark * 7.0)
    wc = len(t.split())
    if wc < 6:
        base -= 12.0
    return float(max(5.0, min(100.0, base)))


def final_answer_score_weighted(
    relevance: float,
    clarity: float,
    langq: float,
    conf: float,
) -> float:
    return float(
        max(
            0.0,
            min(
                100.0,
                relevance * 0.35 + clarity * 0.20 + langq * 0.20 + conf * 0.25,
            ),
        )
    )


def is_correct_heuristic(relevance: float, transcript: str, question_text: str) -> bool:
    if _is_transcription_failed_marker(transcript):
        return False
    if _is_mock_transcript(transcript):
        return False
    if relevance >= 70.0:
        return True
    q_tokens = _tokenize_multilingual(question_text)
    t_tokens = _tokenize_multilingual(transcript)
    if not q_tokens:
        return relevance >= 58.0
    overlap = len(q_tokens & t_tokens) / max(len(q_tokens), 1)
    return overlap >= 0.15 and relevance >= 54.0


def evaluation_comment_line(
    relevance: float,
    clarity: float,
    langq: float,
    conf: float,
    is_ok: bool,
) -> str:
    parts = []
    if is_ok:
        parts.append("Réponse globalement alignée avec la question.")
    else:
        parts.append("Réponse partielle ou peu ancrée dans les attendus de la question.")
    if clarity < 45:
        parts.append("Structure orale peu claire.")
    elif clarity >= 72:
        parts.append("Propos assez structurés.")
    if conf < 42:
        parts.append("Signes d'hésitation marqués.")
    elif conf >= 70:
        parts.append("Ton relativement assuré.")
    if langq < 45:
        parts.append("Richesse lexicale limitée.")
    line = " ".join(parts[:2])
    return (line[:320] + "…") if len(line) > 320 else line


def analyze_answer_row(
    question_text: str,
    duration_seconds: int,
    audio_path: Path | None = None,
    name_context: dict[str, Any] | None = None,
    *,
    relevance_use_llm: bool = True,
) -> dict[str, object]:
    print("START ANALYSIS", flush=True)
    settings = get_settings()
    lang: str | None = None
    tconf: float | None = None
    source = SOURCE_MOCK

    transcript_language_raw: str | None = None

    if audio_path is not None and audio_path.is_file():
        print("TRANSCRIPTION START", flush=True)
        out = transcribe_audio(audio_path, settings, duration_seconds, question_text)
        print("TRANSCRIPTION DONE", flush=True)
        transcript = out.text or ""
        source = out.source
        lang = out.language
        tconf = out.confidence
        if transcript.strip() and not _is_transcription_failed_marker(transcript):
            transcript = _normalize_transcript_unicode_minimal(transcript)
            transcript = align_proper_names_from_context(transcript, question_text)
            surf_pre = detect_transcript_language(transcript, question_text)
            if surf_pre in ("fr", "en"):
                transcript = _polish_latin_transcript_fr_en(transcript, surf_pre)
            if name_context:
                ctx = dict(name_context)
                ctx.setdefault("question_text", question_text)
                t_names = improve_names_from_context(transcript, ctx)
                if t_names != transcript:
                    logger.info("Names correction applied")
                    transcript = t_names
            lang = _finalize_stored_language(transcript, out.whisper_language_raw, question_text)
            transcript_language_raw = detect_transcript_language(transcript, question_text)
            logger.info(
                "oral_answer_analysis: final transcript len=%s stored_lang=%s detected=%s",
                len(transcript),
                lang,
                transcript_language_raw,
            )
        else:
            transcript_language_raw = out.detected_surface_lang
        if _is_transcription_failed_marker(transcript):
            logger.error(
                "oral_answer_analysis: transcript is TRANSCRIPTION_FAILED_MARKER (source=%s)",
                source,
            )
        logger.info(
            "oral_answer_analysis: transcript source=%s len=%s lang=%s raw_lang=%s",
            source,
            len(transcript),
            lang,
            transcript_language_raw,
        )
    else:
        transcript = mock_transcribe(duration_seconds, question_text)
        logger.warning("oral_answer_analysis: MOCK (pas de fichier audio)")

    if lang in (None, "unknown") and transcript:
        lang = _finalize_stored_language(transcript, None, question_text)
    if tconf is None:
        tconf = _confidence_heuristic(transcript, source, duration_seconds)

    hes = hesitation_score_combined(duration_seconds, transcript)
    try:
        if relevance_use_llm:
            print("AI ANALYSIS START", flush=True)
        rel = relevance_score_from_text(transcript, question_text, use_llm=relevance_use_llm)
        if relevance_use_llm:
            print("AI ANALYSIS DONE", flush=True)
    except Exception as exc:
        logger.exception("AI relevance failed, fallback used: %s", exc)
        # Fallback demandé : ne jamais bloquer l’UX si l’IA est indisponible
        rel = 50.0
    coherence = compute_text_coherence_score(transcript)
    clarity = clarity_score_from_text(transcript)
    langq = language_quality_score_from_text(transcript)
    aconf = answer_confidence_score_from_signals(hes, transcript)
    final = final_answer_score_weighted(rel, clarity, langq, aconf)
    ok = is_correct_heuristic(rel, transcript, question_text)
    comment = evaluation_comment_line(rel, clarity, langq, aconf, ok)

    logger.info(
        "analyze_answer_row: final transcript_len=%s provider_used=%s",
        len(transcript or ""),
        source,
    )

    return {
        # Champs de fallback utiles côté intégrations (non intrusifs)
        "score": 50 if source == SOURCE_FAILED else round(final, 2),
        "feedback": "Analyse temporairement indisponible." if source == SOURCE_FAILED else "",
        "transcription": transcript or "",
        "transcript": transcript,
        "transcript_language": lang,
        "transcript_confidence": round(tconf, 2),
        "hesitation_score": round(hes, 2),
        "relevance_score": round(rel, 2),
        "coherence_score": round(coherence, 2),
        "clarity_score": round(clarity, 2),
        "language_quality_score": round(langq, 2),
        "confidence_score": round(aconf, 2),
        "final_answer_score": round(final, 2),
        "is_correct": ok,
        "evaluation_comment": comment,
        "transcription_source": source,
        "transcript_language_raw": transcript_language_raw,
    }


def apply_batch_relevance_to_analysis(
    base: dict[str, object],
    relevance_override: float,
    question_text: str,
    transcript: str,
) -> dict[str, object]:
    """
    Recalcule scores dépendants de la pertinence après une note agrégée (appel LLM unique en fin de session).
    """
    rel = float(max(0.0, min(100.0, relevance_override)))
    clarity = float(base.get("clarity_score") or 0.0)
    langq = float(base.get("language_quality_score") or 0.0)
    aconf = float(base.get("confidence_score") or 0.0)
    final = final_answer_score_weighted(rel, clarity, langq, aconf)
    ok = is_correct_heuristic(rel, transcript, question_text)
    comment = evaluation_comment_line(rel, clarity, langq, aconf, ok)
    out = dict(base)
    out["relevance_score"] = round(rel, 2)
    out["final_answer_score"] = round(final, 2)
    out["is_correct"] = ok
    out["evaluation_comment"] = comment
    return out


def analyze_transcript_only(
    question_text: str,
    transcript: str,
    duration_seconds: int,
    *,
    use_relevance_llm: bool = True,
) -> dict[str, object]:
    """
    Même logique de scores que `analyze_answer_row`, sans fichier audio
    (réponses déjà transcrites en base ou re-calcul rapport).
    Si ``use_relevance_llm`` est False, aucun appel Groq pour la pertinence (agrégat final hors ligne).
    """
    duration_seconds = max(1, min(600, int(duration_seconds or 1)))
    transcript = _normalize_transcript_unicode_minimal((transcript or "").strip())
    transcript = align_proper_names_from_context(transcript, question_text)
    surf0 = detect_transcript_language(transcript, question_text)
    if surf0 in ("fr", "en"):
        transcript = _polish_latin_transcript_fr_en(transcript, surf0)
    if len(transcript) < 2:
        return {
            "transcript": transcript,
            "transcript_language": None,
            "transcript_language_raw": None,
            "transcript_confidence": 12.0,
            "hesitation_score": float(hesitation_score_combined(duration_seconds, transcript)),
            "relevance_score": 8.0,
            "coherence_score": 0.0,
            "clarity_score": 10.0,
            "language_quality_score": 10.0,
            "confidence_score": 15.0,
            "final_answer_score": 10.0,
            "is_correct": False,
            "evaluation_comment": "Transcription vide ou trop courte pour évaluer.",
            "transcription_source": "text_only",
        }

    lang = _finalize_stored_language(transcript, None, question_text)
    tr_raw = detect_transcript_language(transcript, question_text)
    tconf = _confidence_heuristic(transcript, SOURCE_MOCK, duration_seconds)
    hes = hesitation_score_combined(duration_seconds, transcript)
    rel = relevance_score_from_text(transcript, question_text, use_llm=use_relevance_llm)
    coherence = compute_text_coherence_score(transcript)
    clarity = clarity_score_from_text(transcript)
    langq = language_quality_score_from_text(transcript)
    aconf = answer_confidence_score_from_signals(hes, transcript)
    final = final_answer_score_weighted(rel, clarity, langq, aconf)
    ok = is_correct_heuristic(rel, transcript, question_text)
    comment = evaluation_comment_line(rel, clarity, langq, aconf, ok)

    return {
        "transcript": transcript,
        "transcript_language": lang,
        "transcript_confidence": round(tconf, 2),
        "hesitation_score": round(hes, 2),
        "relevance_score": round(rel, 2),
        "coherence_score": round(coherence, 2),
        "clarity_score": round(clarity, 2),
        "language_quality_score": round(langq, 2),
        "confidence_score": round(aconf, 2),
        "final_answer_score": round(final, 2),
        "is_correct": ok,
        "evaluation_comment": comment,
        "transcription_source": "text_only",
        "transcript_language_raw": tr_raw,
    }


def _lexical_diversity_score(transcript: str) -> float:
    """Diversité lexicale 0–100 (indicateur prudent sur un échantillon court)."""
    t = (transcript or "").strip()
    words = re.findall(
        r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+",
        t.lower(),
    )
    n = len(words)
    if n < 6:
        return max(18.0, min(55.0, n * 7.5))
    uniq = len(set(words))
    ratio = uniq / max(n, 1)
    return float(max(22.0, min(100.0, ratio * 100.0)))


def _answer_length_adequacy_score(rows: list) -> float:
    """Longueur moyenne des réponses (mots) — ni trop court ni trop long."""
    wcs: list[int] = []
    for r in rows:
        tt = (getattr(r, "transcript_text", None) or "").strip()
        if len(tt) < 3:
            continue
        wcs.append(len(re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", tt)))
    if not wcs:
        return 42.0
    mw = sum(wcs) / len(wcs)
    # Cible raisonnable : ~25–120 mots par réponse
    if mw < 12:
        return max(25.0, 28.0 + mw * 1.2)
    if mw <= 95:
        return min(100.0, 58.0 + mw * 0.35)
    return max(55.0, 92.0 - (mw - 95) * 0.15)


def _coherence_across_answers_score(finals: list[float]) -> float:
    """Cohérence : écart modéré entre les scores de réponses = profil plus lisible."""
    if len(finals) < 2:
        return 58.0
    m = sum(finals) / len(finals)
    var = sum((x - m) ** 2 for x in finals) / len(finals)
    std = var**0.5
    # std faible → réponses homogènes ; std très élevé → expérience contrastée
    return float(max(35.0, min(92.0, 78.0 - min(40.0, std * 1.1))))


def _aggregate_language_proficiency_index(
    langq_avg: float | None,
    clar_avg: float | None,
    tc_avg: float | None,
    lexical_avg: float,
    length_score: float,
    coherence_score: float,
) -> float:
    """Indice 0–100 interne pour niveau de langue (prudent, multi-signaux)."""
    lq = float(langq_avg) if langq_avg is not None else 46.0
    cl = float(clar_avg) if clar_avg is not None else 46.0
    tc = float(tc_avg) if tc_avg is not None else 48.0
    return float(
        max(
            0.0,
            min(
                100.0,
                lq * 0.26
                + cl * 0.22
                + tc * 0.14
                + lexical_avg * 0.16
                + length_score * 0.12
                + coherence_score * 0.10,
            ),
        )
    )


def _qualitative_level_from_index(idx: float) -> tuple[str, str]:
    """
    Libellé qualitatif + repère CECRL unique approximatif (prudent).
    Retourne (libellé, A1..C2).
    """
    if idx < 26:
        return "Très limité", "A1"
    if idx < 41:
        return "Faible", "A2"
    if idx < 55:
        return "Moyen", "B1"
    if idx < 71:
        return "Bon", "B2"
    if idx < 86:
        return "Très bon", "C1"
    return "Maîtrise avancée", "C2"


_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _normalize_cefr(level: str | None) -> str:
    if not level:
        return "B1"
    s = str(level).strip().upper()
    s = re.sub(r"\s+", "", s)
    for x in _CEFR_ORDER:
        if s == x:
            return x
    m = re.search(r"(A1|A2|B1|B2|C1|C2)", s)
    if m:
        return m.group(1)
    return "B1"


def _cefr_index(level: str) -> int:
    lvl = _normalize_cefr(level)
    try:
        return _CEFR_ORDER.index(lvl)
    except ValueError:
        return 2


def _cefr_min(a: str, b: str) -> str:
    return _CEFR_ORDER[min(_cefr_index(a), _cefr_index(b))]


def _cefr_down_one(level: str, steps: int = 1) -> str:
    i = _cefr_index(level)
    return _CEFR_ORDER[max(0, i - max(1, steps))]


def _cefr_to_proficiency_index(level: str) -> float:
    m = {
        "A1": 22.0,
        "A2": 34.0,
        "B1": 48.0,
        "B2": 62.0,
        "C1": 76.0,
        "C2": 88.0,
    }
    return float(m.get(_normalize_cefr(level), 50.0))


def _stored_code_to_fr_label(code: str) -> str:
    return {
        "fr": "Français",
        "en": "Anglais",
        "ar_msa": "Arabe (MSA)",
        "ar_darija": "Darija (marocain)",
    }.get(code, "Français")


def _session_concat_transcripts(answered_rows: list, max_chars: int = 8000) -> str:
    parts: list[str] = []
    for r in answered_rows:
        tt = (getattr(r, "transcript_text", None) or "").strip()
        if not tt or _is_transcription_failed_marker(tt) or _is_mock_transcript(tt):
            continue
        parts.append(tt)
    blob = "\n".join(parts)
    return blob[:max_chars]


def _count_words_transcript(t: str) -> int:
    return len(
        re.findall(
            r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+",
            (t or "").strip().lower(),
        )
    )


def _session_word_count(answered_rows: list) -> int:
    n = 0
    for r in answered_rows:
        n += _count_words_transcript(getattr(r, "transcript_text", None) or "")
    return n


def _dominant_stored_code_session(
    insights: list[dict[str, object]],
    answered_rows: list,
) -> str:
    """
    Une seule langue dominante parmi fr, en, ar_msa, ar_darija (jamais unknown).
    """
    blob = _session_concat_transcripts(answered_rows)
    if len(blob.strip()) >= 2:
        det = detect_transcript_language(blob, None)
        code = _heuristic_to_stored_code(det)
        if code != "unknown":
            return code
        fin = _finalize_stored_language(blob, None, None)
        if fin != "unknown":
            return fin
    langs: list[str] = []
    for ins in insights:
        v = ins.get("transcript_language")
        if v:
            s = str(v).strip()
            if s and s not in ("unknown", "mixed", ""):
                langs.append(s)
    if langs:
        return Counter(langs).most_common(1)[0][0]
    return "fr"


def _reconcile_llm_language(
    dom: str,
    llm_lang: str | None,
    llm_conf: float | None,
    blob: str,
) -> str:
    valid = {"fr", "en", "ar_msa", "ar_darija"}
    if dom not in valid:
        dom = "fr"
    raw = (llm_lang or "").strip().lower().replace("-", "_")
    if raw in ("ar", "arabic", "msa"):
        raw = "ar_msa"
    if raw == "darija":
        raw = "ar_darija"
    if raw not in valid:
        return dom
    ar_chars = len(re.findall(r"[\u0600-\u06FF]", blob))
    lat_chars = len(re.findall(r"[A-Za-zÀ-ÿ]", blob))
    total = ar_chars + lat_chars + 1e-6
    if ar_chars / total >= 0.28:
        if dom in ("ar_msa", "ar_darija"):
            return dom
        if raw in ("ar_msa", "ar_darija"):
            return raw
        return dom
    conf = float(llm_conf or 0.0)
    if conf >= 0.52 and raw in ("fr", "en"):
        return raw
    return dom


def _apply_cefr_post_rules(
    level: str,
    total_words: int,
    hes_avg: float | None,
) -> str:
    """
    Plafonds réalistes : réponses très courtes, hésitation forte.
    """
    lev = _normalize_cefr(level)
    if total_words < 8:
        lev = _cefr_min(lev, "B1")
    if total_words < 25:
        lev = _cefr_min(lev, "B2")
    if total_words <= 3:
        lev = _cefr_min(lev, "A2")
    if hes_avg is not None:
        if hes_avg >= 72:
            lev = _cefr_down_one(lev, 2)
        elif hes_avg >= 58:
            lev = _cefr_down_one(lev, 1)
    return lev


def evaluate_language_level_llm(transcript: str, settings: Settings) -> dict[str, Any] | None:
    """
    Évaluation niveau oral via Groq : langue dominante, CECRL, justification courte (JSON).
    """
    api_key = _groq_api_key(settings)
    blob = (transcript or "").strip()
    if not api_key or len(blob) < 3:
        return None
    model = (settings.GROQ_MODEL or "llama-3.1-70b-versatile").strip()
    excerpt = blob[:6000]
    system = (
        "You are an expert oral proficiency assessor for hiring interviews. "
        "Output a single JSON object only, no markdown or commentary."
    )
    user_prompt = f"""Evaluate this spoken interview answer transcript (possibly several answers concatenated).

Tasks:
1) Detect the SINGLE dominant language. Use exactly one of: fr, en, ar_msa, ar_darija
   (ar_msa = Modern Standard Arabic in Arabic script or formal MSA; ar_darija = Moroccan Darija, including Latin-chat style).
2) Assign an oral CEFR level: one of A1, A2, B1, B2, C1, C2. For Arabic, use the same CEFR scale as approximate oral proficiency.
3) Be strict and realistic: short, simple self-introductions or single-clause answers must NOT map to C1/C2.
4) confidence: number between 0 and 1.
5) rationale: exactly one concise sentence in French (strengths and limits of the production).

Transcript:
\"\"\"
{excerpt}
\"\"\"

Return JSON with keys: language, level, confidence, rationale"""
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            temperature=0.12,
            max_tokens=420,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = (completion.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        logger.warning("evaluate_language_level_llm failed: %s", exc)
        return None


def _language_dominant_label_from_insights(insights: list[dict[str, object]]) -> str | None:
    langs: list[str] = []
    for ins in insights:
        v = ins.get("transcript_language")
        if v:
            s = str(v).strip()
            if s:
                langs.append(s)
    if not langs:
        return None
    c = Counter(langs)
    top = c.most_common(1)[0][0]
    labels = {
        "fr": "Français",
        "en": "Anglais",
        "ar_msa": "Arabe (MSA)",
        "ar_darija": "Darija (marocain)",
        "ber": "Berbère (indice)",
        "mixed": "Usage mixte",
        "unknown": "Français (estimation)",
    }
    if len(c) >= 2:
        second_n = c.most_common(2)[1][1]
        if second_n >= max(2, len(langs) // 3):
            return "Profil multilingue (estimation)"
    return labels.get(top, top)


def build_language_level_global_text(
    insights: list[dict[str, object]],
    answered_rows: list,
    langq_avg: float | None,
    clar_avg: float | None,
    tc_avg: float | None,
    finals: list[float],
    hes_avg: float | None = None,
    *,
    skip_llm: bool = False,
) -> tuple[str | None, float | None]:
    """
    Texte pour `tests_oraux.language_level_global` : niveau CECRL + langue dominante + brève justification.
    Groq (si clé configurée) pour niveau et formulation ; sinon agrégat heuristique + mêmes garde-fous.
    Si ``skip_llm`` est True (ex. niveau déjà fourni par l’agrégat final), pas d’appel Groq ici.
    """
    settings = get_settings()
    blob = _session_concat_transcripts(answered_rows)
    total_words = _session_word_count(answered_rows)
    dom_code = _dominant_stored_code_session(insights, answered_rows)
    lang_label = _stored_code_to_fr_label(dom_code)

    lex_scores = [
        _lexical_diversity_score(getattr(r, "transcript_text", None) or "")
        for r in answered_rows
    ]
    lexical_avg = sum(lex_scores) / len(lex_scores) if lex_scores else 48.0
    length_score = _answer_length_adequacy_score(answered_rows)
    coherence_score = _coherence_across_answers_score(finals) if finals else 52.0

    idx = _aggregate_language_proficiency_index(
        langq_avg,
        clar_avg,
        tc_avg,
        lexical_avg,
        length_score,
        coherence_score,
    )
    _, cefr_heur = _qualitative_level_from_index(idx)

    llm_data: dict[str, Any] | None = None
    if (
        not skip_llm
        and blob.strip()
        and total_words >= 2
        and _groq_api_key(settings)
    ):
        llm_data = evaluate_language_level_llm(blob, settings)

    if llm_data:
        try:
            llm_conf = float(llm_data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            llm_conf = 0.0
        reconciled = _reconcile_llm_language(
            dom_code,
            str(llm_data.get("language") or "").strip() or None,
            llm_conf,
            blob,
        )
        lang_label = _stored_code_to_fr_label(reconciled)
        level_out = _apply_cefr_post_rules(
            str(llm_data.get("level") or cefr_heur),
            total_words,
            hes_avg,
        )
        rationale = (str(llm_data.get("rationale") or llm_data.get("justification") or "")).strip()
        if not rationale:
            qual_fb, _ = _qualitative_level_from_index(_cefr_to_proficiency_index(level_out))
            rationale = f"Niveau {qual_fb.lower()} d’après les indices disponibles."
        rationale = rationale[:280]
        text = f"Niveau oral : {level_out} ({lang_label}) — {rationale}"
        prof_idx = round(_cefr_to_proficiency_index(level_out), 2)
        return text, prof_idx

    level_out = _apply_cefr_post_rules(cefr_heur, total_words, hes_avg)
    qual_fb, _ = _qualitative_level_from_index(_cefr_to_proficiency_index(level_out))
    text = (
        f"Niveau oral : {level_out} ({lang_label}) — "
        f"{qual_fb.lower()} (évaluation heuristique locale, LLM indisponible)."
    )
    prof_idx = round(_cefr_to_proficiency_index(level_out), 2)
    return text, prof_idx


def _mean_and_spread(vals: list[float]) -> tuple[float | None, float | None]:
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in vals) / len(vals)
    return m, var**0.5


def _build_soft_skills_summary(
    comm_avg: float | None,
    clar_avg: float | None,
    tech_avg: float | None,
    mean_relevance: float | None,
    conf: float | None,
    stress: float | None,
    glob: float | None,
    hes_avg: float | None,
    *,
    relevance_scores: list[float],
    hesitation_scores: list[float],
    answer_durations_sec: list[int],
    finals: list[float],
    eye_contact_global: float | None,
    cheating_flags_norm: dict[str, Any],
    oral: TestOral,
) -> str:
    """
    2–3 phrases max, ton RH, ancrées dans les métriques réelles (pas de formulations interchangeables).
    L’ordre des idées varie selon les écarts observés (pertinence vs fluidité vs regard).
    """
    cl = clar_avg if clar_avg is not None else comm_avg
    cl = float(cl) if cl is not None else 50.0
    mr = float(mean_relevance) if mean_relevance is not None else (
        float(tech_avg) if tech_avg is not None else 50.0
    )
    co = float(conf) if conf is not None else 50.0
    st = float(stress) if stress is not None else 48.0
    h_avg = float(hes_avg) if hes_avg is not None else 48.0
    eye = float(eye_contact_global) if eye_contact_global is not None else 52.0
    gglob = float(glob) if glob is not None else 55.0

    rel_mean, rel_std = _mean_and_spread([float(x) for x in relevance_scores])
    if rel_mean is None:
        rel_mean = mr
        rel_std = 0.0
    hes_mean, hes_std = _mean_and_spread([float(x) for x in hesitation_scores])
    if hes_mean is None:
        hes_mean = h_avg
        hes_std = 0.0

    durs = [int(x) for x in answer_durations_sec if x is not None and int(x) >= 0]
    avg_dur = sum(durs) / len(durs) if durs else None

    fin_mean, fin_std = _mean_and_spread([float(x) for x in finals])
    if fin_mean is None:
        fin_mean = 50.0
        fin_std = 0.0

    gaze = cheating_flags_norm.get("gaze") if isinstance(cheating_flags_norm, dict) else {}
    gaze = gaze if isinstance(gaze, dict) else {}
    gaze_samples = int(gaze.get("samples") or 0)
    gaze_off_ratio = compute_gaze_off_ratio(cheating_flags_norm)

    # Phrases atomiques (contenu différent selon seuils réels)
    def sentence_fluidity() -> str:
        parts_d: list[str] = []
        if hes_mean < 38:
            parts_d.append(
                "Le débit est globalement fluide, avec un faible niveau d’hésitation détecté sur l’audio."
            )
        elif hes_mean < 52:
            parts_d.append(
                "L’expression reste compréhensible, avec des hésitations modérées cohérentes avec un échange spontané."
            )
        else:
            parts_d.append(
                "Des hésitations marquées et répétées ressortent sur plusieurs réponses, ce qui alourdit la fluidité perçue."
            )
        if hes_std is not None and hes_std >= 14:
            parts_d.append(" L’intensité de ces hésitations varie sensiblement d’une question à l’autre.")
        if avg_dur is not None:
            if avg_dur < 14:
                parts_d.append(
                    " Les temps de réponse sont en moyenne courts, ce qui limite la densité d’argumentation."
                )
            elif avg_dur > 95:
                parts_d.append(
                    " Les réponses tendent à s’étirer dans le temps, avec un rythme parfois lent."
                )
        return "".join(parts_d).strip()

    def sentence_relevance() -> str:
        if rel_mean >= 70 and (rel_std or 0) < 12:
            return (
                "Les réponses restent globalement alignées sur les questions posées, avec une pertinence stable."
            )
        if rel_mean >= 62 and (rel_std or 0) >= 14:
            return (
                "La pertinence est correcte en moyenne mais inégale : certaines réponses sont nettement plus ciblées que d’autres."
            )
        if rel_mean >= 62:
            return (
                "Le lien avec les objectifs des questions est globalement satisfaisant, sans écarts majeurs."
            )
        if rel_mean >= 48:
            return (
                "La pertinence est seulement partielle : plusieurs réponses ne couvrent qu’une partie des attendus ou restent génériques."
            )
        return (
            "Plusieurs réponses s’éloignent des questions ou n’en traitent qu’un aspect limité, ce qui fragilise l’adéquation globale."
        )

    def sentence_clarity_structure() -> str:
        if cl >= 68 and (fin_std or 0) < 12:
            return (
                "La clarté perçue est bonne et la qualité des réponses est relativement homogène d’un tour de parole à l’autre."
            )
        if cl >= 68:
            return (
                "Les propos sont plutôt clairs, mais la qualité des réponses fluctue selon les questions."
            )
        if cl >= 52:
            return (
                "La clarté est correcte, avec une structuration des idées encore perfectible sur certains segments."
            )
        return (
            "La clarté et la structuration des réponses demeurent des axes prioritaires : le message est parfois difficile à suivre."
        )

    def sentence_confidence_eye(trim_gaze_detail: bool = False) -> str:
        """Si `trim_gaze_detail`, pas de détail regard (réservé à une phrase « comportement » séparée)."""
        if trim_gaze_detail:
            if co >= 64:
                return (
                    "Les scores agrégés de confiance (voix, fluidité, stabilité de session) restent dans une fourchette soutenue."
                )
            if co >= 52:
                return (
                    "Les scores agrégés de confiance se situent dans une fourchette correcte, sans pic d’assurance marqué."
                )
            return (
                "Les scores agrégés de confiance restent modestes au regard des autres indicateurs calculés."
            )
        bits: list[str] = []
        if co >= 66 and eye >= 56 and hes_mean < 52:
            bits.append(
                "L’aisance perçue est bonne, avec une tenue de parole cohérente avec un niveau de confiance satisfaisant"
            )
        elif co >= 58:
            bits.append("L’aisance reste dans une fourchette correcte au regard des indicateurs de confiance calculés")
        else:
            bits.append(
                "La confiance perçue reste modeste au regard des scores agrégés (voix, fluidité, stabilité de session)"
            )
        if eye < 46:
            bits.append(
                ", et le score de maintien du regard vers la caméra est bas, ce qui peut refléter une attention partiellement déportée."
            )
        elif eye < 56:
            bits.append(
                ", avec un engagement visuel vers la caméra correct mais perfectible."
            )
        else:
            bits.append(", avec un engagement visuel vers la caméra plutôt satisfaisant.")
        return "".join(bits)

    def sentence_stress_global() -> str | None:
        if st >= 68 and hes_mean >= 55:
            return (
                "Les indicateurs de stress oral et d’hésitation convergent vers une tension perceptible dans l’échange."
            )
        if st >= 64:
            return (
                "Un niveau de stress technique ou oral élevé ressort des agrégats, pouvant impacter la tenue générale."
            )
        if gglob < 48:
            return (
                "Le score oral global synthétique reste bas, cohérent avec des marges de progression sur plusieurs dimensions à la fois."
            )
        return None

    def sentence_behavior() -> str | None:
        if gaze_samples >= 10 and gaze_off_ratio >= 0.36:
            return (
                "Le suivi du regard indique une part importante d’échantillons « hors cadre », compatible avec une attention moins focalisée sur l’écran."
            )
        if gaze_samples >= 10 and gaze_off_ratio >= 0.22:
            return (
                "Le comportement du regard montre des écarts récurrents par rapport au cadre vidéo, à interpréter avec prudence selon le contexte."
            )
        if (oral.tab_switch_count or 0) >= 3:
            return (
                "Des changements d’onglet répétés ont été enregistrés pendant la session, ce qui peut signaler une dispersion attentionnelle."
            )
        if oral.phone_detected:
            return (
                "La détection d’un objet type téléphone dans le champ caméra a été signalée ; à contextualiser lors de l’analyse du comportement."
            )
        return None

    # Prioriser les axes les plus « atypiques » pour varier l’ordre des phrases
    rel_gap = abs(rel_mean - 55.0)
    hes_gap = abs(hes_mean - 48.0)
    eye_gap = abs(eye - 52.0)
    order_key = (rel_gap, hes_gap, eye_gap, rel_std or 0, fin_std or 0)
    # Ordre cyclique : 6 variantes
    variant = int(sum(order_key) * 7 + len(relevance_scores) * 3) % 6

    pool_primary: list[str] = [sentence_relevance(), sentence_fluidity(), sentence_clarity_structure()]
    if variant % 2 == 0:
        pool_primary = [sentence_fluidity(), sentence_relevance(), sentence_clarity_structure()]
    if variant % 3 == 0:
        pool_primary = [sentence_clarity_structure(), sentence_relevance(), sentence_fluidity()]

    beh = sentence_behavior()
    extra = sentence_stress_global()
    secondary = sentence_confidence_eye(trim_gaze_detail=beh is not None)

    chosen: list[str] = []
    chosen.append(pool_primary[0])
    second = pool_primary[1]
    if second not in chosen:
        chosen.append(second)

    # 3ᵉ phrase : stress session si fort, sinon confiance (avec ou sans détail regard), sinon comportement caméra / onglets
    third_options: list[str] = []
    if extra:
        third_options.append(extra)
    third_options.append(secondary)
    if beh:
        third_options.append(beh)

    for cand in third_options:
        if len(chosen) >= 3:
            break
        if cand and cand not in chosen:
            chosen.append(cand)

    if len(chosen) < 2:
        chosen.append(pool_primary[2])

    text = " ".join(chosen[:3]).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 920:
        text = text[:917] + "…"
    return text


def _word_count_multilingual(transcript: str) -> int:
    t = transcript or ""
    return len(re.findall(r"[\wàâäéèêëïîôùûç'-]+|[\u0600-\u06FF]+", t, re.I))


def _clamp_0_100(value: float) -> float:
    return float(max(0.0, min(100.0, value)))


def _transcript_valid_for_session_ratio(text: str | None) -> bool:
    """Transcription exploitable pour le ratio de qualité (données réelles, pas marqueur d’échec)."""
    t = (text or "").strip()
    if not t:
        return False
    if TRANSCRIPTION_FAILED_MARKER in t or _is_transcription_failed_marker(t):
        return False
    return True


def _duration_component_global(avg_duration_sec: float) -> float:
    """Paliers de durée moyenne (secondes) pour le score global."""
    d = float(avg_duration_sec)
    if d < 5:
        return 30.0
    if d < 10:
        return 60.0
    if d < 20:
        return 85.0
    return 100.0


def _duration_confidence_scalar(avg_duration_sec: float) -> float:
    """Confiance liée à la durée moyenne des réponses (secondes)."""
    d = float(avg_duration_sec)
    if d >= 8:
        return 100.0
    return _clamp_0_100(d * 10.0)


def _short_answer_stress_penalty(rows: Sequence[OralTestQuestion]) -> float:
    """Pénalité si beaucoup de réponses très courtes (< 8 s)."""
    if not rows:
        return 0.0
    short = sum(1 for r in rows if int(r.answer_duration_seconds or 0) < 8)
    return float(min(35.0, (short / len(rows)) * 28.0))


def compute_session_stress_detailed(
    hesitation_avg: float | None,
    rapid_motion_count: int,
    gaze_off_ratio: float,
    face_not_visible_count: int,
    *,
    short_answer_penalty: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """
    Stress 0–100 : hésitation, mouvements rapides (échelle 0–100), instabilité regard,
    visage absent, réponses trop courtes.
    """
    h_term = float(hesitation_avg) * 0.35 if hesitation_avg is not None else 0.0
    r = min(max(0, int(rapid_motion_count)), 10)
    rapid_motion_score = float(r * 10.0)
    gaze_instability_score = _clamp_0_100(float(gaze_off_ratio) * 100.0)
    fnv = max(0, int(face_not_visible_count))
    fnv_term = float(fnv * 5.0)
    sp = float(short_answer_penalty)
    combined = (
        h_term
        + rapid_motion_score * 0.25
        + gaze_instability_score * 0.20
        + fnv_term
        + sp
    )
    stress = _clamp_0_100(combined)
    breakdown: dict[str, Any] = {
        "hesitation_term": round(h_term, 2),
        "rapid_motion_score": round(rapid_motion_score, 2),
        "gaze_instability_score": round(gaze_instability_score, 2),
        "face_not_visible_term": round(fnv_term, 2),
        "short_answer_penalty": round(sp, 2),
    }
    return stress, breakdown


def compute_session_confidence_detailed(
    hesitation_avg: float | None,
    gaze_quality_score: float,
    movement_stability_score: float,
    duration_confidence: float,
    valid_transcript_ratio: float,
    suspicion_level: str,
    oral: TestOral,
) -> tuple[float, dict[str, Any]]:
    """
    Confiance 0–100 : verbal, qualité regard (score métier), stabilité mouvement,
    durée, transcripts valides ; pénalités suspicion / téléphone / autre personne.
    """
    if hesitation_avg is None:
        verbal = 55.0
    else:
        verbal = _clamp_0_100(100.0 - float(hesitation_avg))
    gq = _clamp_0_100(float(gaze_quality_score))
    ms = _clamp_0_100(float(movement_stability_score))
    dur_c = _clamp_0_100(float(duration_confidence))
    tr = max(0.0, min(1.0, float(valid_transcript_ratio)))
    base = (
        verbal * 0.30
        + gq * 0.25
        + ms * 0.15
        + dur_c * 0.15
        + tr * 100.0 * 0.15
    )
    pen = 0.0
    sl = str(suspicion_level or "").upper()
    if sl == "HIGH":
        pen += 20.0
    elif sl == "MEDIUM":
        pen += 8.0
    if oral.phone_detected:
        pen += 15.0
    if oral.other_person_detected:
        pen += 20.0
    conf = _clamp_0_100(base - pen)
    breakdown: dict[str, Any] = {
        "base_weighted": round(base, 2),
        "penalties": round(pen, 2),
        "verbal_component": round(verbal, 2),
        "gaze_quality": round(gq, 2),
        "movement_stability": round(ms, 2),
        "duration_confidence": round(dur_c, 2),
        "valid_transcript_ratio": round(tr, 4),
        "suspicion_level": sl,
    }
    return conf, breakdown


def compute_oral_global_score(
    questions: Sequence[OralTestQuestion],
    proctoring_flags: dict[str, Any],
    oral: TestOral,
) -> dict[str, Any]:
    """
    Pipeline production : enrichit ``estimates``, calcule stress / confiance / score global.
    Pondération globale : pertinence 60 %, fluidité 15 %, transcript 10 %, durée 10 %, proctoring 5 %.
    """
    rows = list(questions)
    if not isinstance(proctoring_flags, dict):
        flags: dict[str, Any] = normalize_proctoring_flags(proctoring_flags)
    else:
        flags = proctoring_flags

    if not rows:
        empty = {
            "score_oral_global": 0.0,
            "confidence_score": 0.0,
            "stress_score": 0.0,
            "score_breakdown": {
                "relevance": 0.0,
                "fluency": 0.0,
                "duration": 0.0,
                "transcript": 0.0,
                "proctoring": 0.0,
                "penalties": 0.0,
                "raw_weighted": 0.0,
            },
            "confidence_breakdown": {},
            "stress_breakdown": {},
        }
        return empty

    est = dict(flags.get("estimates") or {})
    est.update(merge_proctoring_estimates_enriched(oral, flags))
    flags["estimates"] = est

    rels = [float(r.relevance_score) for r in rows if r.relevance_score is not None]
    relevance_avg = sum(rels) / len(rels) if rels else 0.0

    hess_list = [float(r.hesitation_score) for r in rows if r.hesitation_score is not None]
    hesitation_avg: float | None = (
        sum(hess_list) / len(hess_list) if hess_list else None
    )

    durs = [int(r.answer_duration_seconds or 0) for r in rows]
    duration_avg = sum(durs) / max(len(durs), 1) if durs else 0.0

    valid_n = sum(1 for r in rows if _transcript_valid_for_session_ratio(r.transcript_text))
    valid_transcript_ratio = valid_n / max(len(rows), 1)

    gaze_b = flags.get("gaze") if isinstance(flags.get("gaze"), dict) else {}
    samples_g = max(0, int(gaze_b.get("samples") or 0))
    g_off = float(gaze_b.get("off_ratio") or est.get("gaze_off_ratio") or 0.0)
    if samples_g < 4:
        g_off = float(est.get("gaze_off_ratio") or g_off)

    ctr = flags.get("counters") if isinstance(flags.get("counters"), dict) else {}
    rapid_motion_count = int(ctr.get("rapid_motion_heartbeat_count") or 0)
    face_not_visible_count = int(ctr.get("face_not_visible_count") or 0)

    gq = est.get("gaze_quality")
    if not isinstance(gq, dict):
        gq = compute_gaze_quality(flags)
    mv = est.get("movement_analysis")
    if not isinstance(mv, dict):
        mv = compute_movement_level(flags, oral)
    pres = est.get("presence_analysis")
    if not isinstance(pres, dict):
        pres = compute_presence_stability(oral, flags)
    susp_obj = est.get("suspicion_assessment")
    if not isinstance(susp_obj, dict):
        susp_obj = compute_suspicion_assessment(oral, flags)
        est["suspicion_assessment"] = susp_obj
        flags["estimates"] = est

    gaze_quality_score = float(gq.get("score") or 0.0)
    movement_stability_score = float(mv.get("stability_score") or 0.0)
    suspicion_level = str(susp_obj.get("level") or est.get("suspicion_risk_level") or "")
    suspicion_numeric = float(susp_obj.get("score") or est.get("suspicion_score") or 0.0)

    short_pen = _short_answer_stress_penalty(rows)
    stress, stress_breakdown = compute_session_stress_detailed(
        hesitation_avg,
        rapid_motion_count,
        g_off,
        face_not_visible_count,
        short_answer_penalty=short_pen,
    )
    dur_conf = _duration_confidence_scalar(duration_avg)
    confidence, confidence_breakdown = compute_session_confidence_detailed(
        hesitation_avg,
        gaze_quality_score,
        movement_stability_score,
        dur_conf,
        valid_transcript_ratio,
        suspicion_level,
        oral,
    )

    relevance_component = _clamp_0_100(relevance_avg)
    if hesitation_avg is None:
        fluency_component = 55.0
    else:
        fluency_component = _clamp_0_100(100.0 - float(hesitation_avg))
    duration_component = _duration_component_global(duration_avg)
    transcript_quality_component = _clamp_0_100(valid_transcript_ratio * 100.0)
    proctoring_component = _clamp_0_100(gaze_quality_score)

    raw_score = (
        relevance_component * 0.60
        + fluency_component * 0.15
        + transcript_quality_component * 0.10
        + duration_component * 0.10
        + proctoring_component * 0.05
    )

    penalty = 0.0
    if oral.phone_detected:
        penalty -= 15.0
    if oral.other_person_detected:
        penalty -= 20.0

    risk = str(suspicion_level or "").upper()
    if risk == "HIGH":
        penalty -= 25.0
    elif risk == "MEDIUM":
        penalty -= 10.0

    score_final = _clamp_0_100(raw_score + penalty)

    score_breakdown = {
        "relevance": round(relevance_component, 2),
        "fluency": round(fluency_component, 2),
        "duration": round(duration_component, 2),
        "transcript": round(transcript_quality_component, 2),
        "proctoring": round(proctoring_component, 2),
        "penalties": round(penalty, 2),
        "raw_weighted": round(raw_score, 2),
    }

    print(
        "PROCTORING SCORE DEBUG:",
        {
            "gaze": gq,
            "movement": mv,
            "presence": pres,
            "suspicion": susp_obj,
            "confidence": round(confidence, 2),
            "stress": round(stress, 2),
        },
        flush=True,
    )
    print(
        "ORAL SCORE DEBUG:",
        {
            "score_oral": round(score_final, 2),
            "confidence": round(confidence, 2),
            "stress": round(stress, 2),
            "penalties": round(penalty, 2),
            "relevance_avg": round(relevance_avg, 2),
            "hesitation_avg": round(hesitation_avg, 2) if hesitation_avg is not None else None,
            "suspicion_score": round(suspicion_numeric, 2),
        },
        flush=True,
    )

    est["confidence_breakdown"] = confidence_breakdown
    est["stress_breakdown"] = stress_breakdown
    flags["estimates"] = est

    return {
        "score_oral_global": round(score_final, 2),
        "confidence_score": round(confidence, 2),
        "stress_score": round(stress, 2),
        "score_breakdown": score_breakdown,
        "confidence_breakdown": confidence_breakdown,
        "stress_breakdown": stress_breakdown,
    }


def compute_oral_score(
    db: Session,
    test_oral_id: UUID,
    *,
    skip_session_language_llm: bool = False,
) -> None:
    oral = db.query(TestOral).filter(TestOral.id == test_oral_id).first()
    if not oral:
        return
    rows = (
        db.query(OralTestQuestion)
        .filter(OralTestQuestion.test_oral_id == test_oral_id)
        .order_by(OralTestQuestion.question_order.asc())
        .all()
    )
    answered = [r for r in rows if r.relevance_score is not None]
    if not answered:
        return

    if oral.eye_contact_score_global is None:
        oral.eye_contact_score_global = compute_eye_contact_score_global_from_flags(
            oral.cheating_flags
        )

    refresh_suspicious_movements_count_from_flags(oral)

    flags = normalize_proctoring_flags(oral.cheating_flags)
    insights: list[dict[str, object]] = []
    finals: list[float] = []
    rels: list[float] = []

    for r in answered:
        ins_raw = get_answer_insight(flags, r.question_order)
        if ins_raw and ins_raw.get("final_answer_score") is not None:
            ins: dict[str, object] = dict(ins_raw)
        else:
            dur = int(r.answer_duration_seconds or 30)
            full = analyze_transcript_only(r.question_text or "", r.transcript_text or "", dur)
            ins = {
                "transcript_language": full.get("transcript_language"),
                "transcript_language_raw": full.get("transcript_language_raw"),
                "transcript_confidence": full.get("transcript_confidence"),
                "clarity_score": full.get("clarity_score"),
                "language_quality_score": full.get("language_quality_score"),
                "confidence_score": full.get("confidence_score"),
                "final_answer_score": full.get("final_answer_score"),
                "is_correct": full.get("is_correct"),
                "evaluation_comment": full.get("evaluation_comment"),
                "transcription_source": full.get("transcription_source"),
            }
        insights.append(ins)
        finals.append(float(ins["final_answer_score"]))
        if r.relevance_score is not None:
            rels.append(float(r.relevance_score))

    audio_score = round(sum(finals) / len(finals), 2)

    clar = [float(i["clarity_score"]) for i in insights if i.get("clarity_score") is not None]
    langqs = [float(i["language_quality_score"]) for i in insights if i.get("language_quality_score") is not None]
    langq_avg: float | None = round(sum(langqs) / len(langqs), 2) if langqs else None
    comm_avg: float | None = None
    if clar or langqs:
        comm_parts: list[float] = []
        if clar:
            comm_parts.append(sum(clar) / len(clar))
        if langqs:
            comm_parts.append(sum(langqs) / len(langqs))
        comm_avg = round(sum(comm_parts) / len(comm_parts), 2)

    tech_parts: list[float] = []
    if rels:
        tech_parts.append(sum(rels) / len(rels))
    correct_n = sum(1 for i in insights if i.get("is_correct") is True)
    tech_parts.append(100.0 * correct_n / max(len(insights), 1))
    tech_avg = round(sum(tech_parts) / len(tech_parts), 2) if tech_parts else None

    hess = [float(r.hesitation_score) for r in answered if r.hesitation_score is not None]
    tconfs = [float(i["transcript_confidence"]) for i in insights if i.get("transcript_confidence") is not None]
    hes_avg = sum(hess) / len(hess) if hess else None
    tc_avg = sum(tconfs) / len(tconfs) if tconfs else None
    clar_avg_f = sum(clar) / len(clar) if clar else None
    mean_rel = sum(rels) / len(rels) if rels else audio_score

    scoring_payload = compute_oral_global_score(answered, flags, oral)
    est = (flags.get("estimates") or {}) if isinstance(flags.get("estimates"), dict) else {}
    ch = est.get("cheating_score")
    try:
        ch_f = float(ch) if ch is not None else None
    except (TypeError, ValueError):
        ch_f = None
    oral.score_oral_global = scoring_payload["score_oral_global"]
    oral.confidence_score = scoring_payload["confidence_score"]
    oral.stress_score = scoring_payload["stress_score"]
    score_breakdown = scoring_payload["score_breakdown"]

    glob = oral.score_oral_global
    conf = oral.confidence_score
    final_decision: str | None = None
    if glob is not None:
        if ch_f is not None and ch_f >= 62 and (glob < 58 or (conf is not None and conf < 45)):
            final_decision = "POOR"
        elif glob >= 72 and (ch_f is None or ch_f < 45) and (conf is None or conf >= 55):
            final_decision = "GOOD"
        elif glob >= 55:
            final_decision = "AVERAGE"
        else:
            final_decision = "POOR"

    lang_txt, prof_idx = build_language_level_global_text(
        insights,
        answered,
        langq_avg,
        clar_avg_f,
        tc_avg,
        finals,
        hes_avg,
        skip_llm=skip_session_language_llm,
    )
    if lang_txt:
        oral.language_level_global = lang_txt

    durs_for_summary = [int(r.answer_duration_seconds or 0) for r in answered]
    oral.soft_skills_summary = _build_soft_skills_summary(
        comm_avg,
        clar_avg_f,
        tech_avg,
        mean_rel,
        oral.confidence_score,
        oral.stress_score,
        oral.score_oral_global,
        hes_avg,
        relevance_scores=rels,
        hesitation_scores=hess,
        answer_durations_sec=durs_for_summary,
        finals=finals,
        eye_contact_global=oral.eye_contact_score_global,
        cheating_flags_norm=flags,
        oral=oral,
    )

    flags[SESSION_SCORES_KEY] = {
        "communication_avg": comm_avg,
        "technical_avg": tech_avg,
        "final_decision": final_decision,
        "scoring_version": 5,
        "score_breakdown": score_breakdown,
        "language_proficiency_index": prof_idx,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    flags["summary_global"] = build_flags_global_summary(oral, flags)
    oral.cheating_flags = flags

    ensure_oral_proctoring_fields(oral)
    db.add(oral)
    db.commit()
    logger.info(
        "compute_oral_score: id=%s global=%s comm=%s tech=%s conf=%s stress=%s decision=%s",
        test_oral_id,
        oral.score_oral_global,
        comm_avg,
        tech_avg,
        oral.confidence_score,
        oral.stress_score,
        final_decision,
    )
