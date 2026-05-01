"""
Génération structurée des questions d'entretien oral : 3 questions fixes obligatoires,
puis questions dynamiques par domaine (offre) et niveau (Junior / Confirmé / Senior).
Persistance dans `oral_test_questions`.
"""
from __future__ import annotations

import logging
import random
import re
import uuid
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.oral_test_question import OralTestQuestion
from app.models.test_oral import TestOral
from app.services.morocco_text_pipeline import apply_pipeline_to_oral_question
from app.services.oral_question_banks import (
    ORAL_FIXED_QUESTIONS,
    DomainKey,
    LevelKey,
    detect_domain,
    get_bank,
    merge_dynamic_pool,
    normalize_level,
)

logger = logging.getLogger(__name__)

MIN_ORAL_QUESTIONS = 3
MAX_ORAL_QUESTIONS = 30


def resolve_total_questions(
    nb_offre: Optional[int],
    nb_body: Optional[int],
) -> int:
    """`nombre_questions_orale` prioritaire ; minimum 3 (questions fixes)."""
    n = nb_offre if nb_offre is not None and nb_offre > 0 else None
    if n is None:
        n = nb_body if nb_body is not None and nb_body > 0 else None
    if n is None:
        n = 20
    n = max(MIN_ORAL_QUESTIONS, min(n, MAX_ORAL_QUESTIONS))
    return n


def _normalize_question_text(q: str) -> str:
    t = re.sub(r"^\s*\d+[\s.)-]+\s*", "", (q or "").strip())
    t = re.sub(r"\s+", " ", t.lower())
    return t.strip()


def _fixed_normalized() -> set[str]:
    return {_normalize_question_text(x) for x in ORAL_FIXED_QUESTIONS}


def _filter_new_questions(
    raw: list[str],
    fixed_norm: set[str],
    seen: set[str],
) -> list[str]:
    out: list[str] = []
    for q in raw:
        s = (q or "").strip()
        n = _normalize_question_text(s)
        if len(s) < 12 or not n or n in fixed_norm or n in seen:
            continue
        seen.add(n)
        out.append(s)
    return out


def _dynamic_pool_primary(domain: DomainKey, level: LevelKey) -> list[str]:
    """Banque adaptée au niveau : domaine + renfort « general » même niveau."""
    return list(merge_dynamic_pool(domain, level))


def _dynamic_pool_fallback_tiers(
    domain: DomainKey,
    level: LevelKey,
) -> list[list[str]]:
    """
    Compléments successifs si le pool principal est trop petit :
    autres niveaux du même domaine, puis autres niveaux du domaine général.
    """
    tiers: list[list[str]] = []
    for lvl in ("junior", "confirme", "senior"):
        if lvl == level:
            continue
        tiers.append(list(get_bank(domain, lvl)))
    if domain != "general":
        for lvl in ("junior", "confirme", "senior"):
            if lvl == level:
                continue
            tiers.append(list(get_bank("general", lvl)))
    return tiers


def build_structured_oral_questions(
    total: int,
    domain: DomainKey,
    level: LevelKey,
    session_id: uuid.UUID,
) -> tuple[list[str], str]:
    """
    Construit la liste finale : 3 fixes + (total - 3) dynamiques mélangées.
    Les dynamiques sont d’abord tirées du niveau cible ; les autres niveaux ne servent qu’en complément.
    Le mélange dépend de `session_id` (ex. `tests_oraux.id`) pour différencier les candidats.
    """
    total = max(MIN_ORAL_QUESTIONS, min(total, MAX_ORAL_QUESTIONS))
    fixed = list(ORAL_FIXED_QUESTIONS)
    dynamic_needed = max(0, total - len(fixed))

    rng = random.Random(session_id.int % (2**63))

    fixed_norm = _fixed_normalized()
    seen: set[str] = set()

    primary = _filter_new_questions(
        _dynamic_pool_primary(domain, level),
        fixed_norm,
        seen,
    )
    rng.shuffle(primary)

    dynamic: list[str] = []
    for q in primary:
        if len(dynamic) >= dynamic_needed:
            break
        dynamic.append(q)

    if len(dynamic) < dynamic_needed:
        for tier in _dynamic_pool_fallback_tiers(domain, level):
            tier_f = _filter_new_questions(tier, fixed_norm, seen)
            rng.shuffle(tier_f)
            for q in tier_f:
                if len(dynamic) >= dynamic_needed:
                    break
                dynamic.append(q)
            if len(dynamic) >= dynamic_needed:
                break

    if len(dynamic) < dynamic_needed:
        logger.warning(
            "oral_questions: pool insuffisant (domain=%s level=%s) — %s/%s",
            domain,
            level,
            len(dynamic),
            dynamic_needed,
        )

    out = fixed + dynamic[:dynamic_needed]
    meta = f"structured:{domain}:{level}"
    return out, meta


def load_or_create_questions_for_test_oral(
    db: Session,
    oral: TestOral,
    job_title: str,
    keywords: str,
    nb_tech: Optional[int],
) -> tuple[list[str], str]:
    """
    Si des lignes existent déjà pour ce test oral, les renvoie (ordre question_order).
    Sinon génère (banques domaine/niveau + 3 fixes), insère et commit.
    """
    existing = (
        db.query(OralTestQuestion)
        .filter(OralTestQuestion.test_oral_id == oral.id)
        .order_by(OralTestQuestion.question_order.asc())
        .all()
    )
    if existing:
        logger.info(
            "oral_questions: lecture base — test_oral_id=%s, %s question(s)",
            oral.id,
            len(existing),
        )
        return [row.question_text for row in existing], "database"

    cand = (
        db.query(Candidature)
        .filter(Candidature.id == oral.id_candidature)
        .first()
    )
    offre: Optional[Offre] = None
    if cand:
        offre = db.query(Offre).filter(Offre.id == cand.offre_id).first()

    nb_offre = offre.nombre_questions_orale if offre else None
    total = resolve_total_questions(nb_offre, nb_tech)

    title = (offre.title if offre and offre.title else job_title) or ""
    profile = (offre.profile if offre else None) or ""
    description = (offre.description_postes if offre else None) or ""
    compet = (offre.competences if offre else None) or ""
    domain_blob = " ".join(
        x for x in (description, compet, keywords) if x
    ).strip()

    domain = detect_domain(title, profile, domain_blob)
    level = normalize_level(offre.level if offre else None)

    texts, source = build_structured_oral_questions(
        total,
        domain,
        level,
        oral.id,
    )

    if not texts:
        texts = list(ORAL_FIXED_QUESTIONS)
        source = "structured:fallback"

    texts = [apply_pipeline_to_oral_question(t) for t in texts]

    for order, text in enumerate(texts, start=1):
        db.add(
            OralTestQuestion(
                id=uuid.uuid4(),
                test_oral_id=oral.id,
                question_order=order,
                question_text=text,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning(
            "oral_questions: insertion concurrente ou contrainte — relecture test_oral_id=%s",
            oral.id,
        )
        retry_rows = (
            db.query(OralTestQuestion)
            .filter(OralTestQuestion.test_oral_id == oral.id)
            .order_by(OralTestQuestion.question_order.asc())
            .all()
        )
        if retry_rows:
            return [row.question_text for row in retry_rows], "database"
        raise

    logger.info(
        "oral_questions: enregistrement base — test_oral_id=%s, %s question(s), source=%s",
        oral.id,
        len(texts),
        source,
    )
    return texts, source


def persist_emergency_fallback_questions(
    db: Session,
    oral: TestOral,
    job_title: str,
    keywords: str,
    nb_tech: Optional[int],
) -> tuple[list[str], str]:
    """
    Si `load_or_create_questions_for_test_oral` lève une exception : insère des questions
    minimales (banque fixe en cycle) pour ne pas bloquer le candidat.
    """
    _ = (job_title, keywords)  # réserve pour enrichissement futur sans changer le schéma
    existing = (
        db.query(OralTestQuestion)
        .filter(OralTestQuestion.test_oral_id == oral.id)
        .order_by(OralTestQuestion.question_order.asc())
        .all()
    )
    if existing:
        return [row.question_text for row in existing], "database"

    cand = (
        db.query(Candidature)
        .filter(Candidature.id == oral.id_candidature)
        .first()
    )
    offre: Optional[Offre] = None
    if cand:
        offre = db.query(Offre).filter(Offre.id == cand.offre_id).first()

    nb_offre = offre.nombre_questions_orale if offre else None
    total = resolve_total_questions(nb_offre, nb_tech)

    base = list(ORAL_FIXED_QUESTIONS)
    texts = [base[i % len(base)] for i in range(total)]
    texts = [apply_pipeline_to_oral_question(t) for t in texts]

    for order, text in enumerate(texts, start=1):
        db.add(
            OralTestQuestion(
                id=uuid.uuid4(),
                test_oral_id=oral.id,
                question_order=order,
                question_text=text,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        retry_rows = (
            db.query(OralTestQuestion)
            .filter(OralTestQuestion.test_oral_id == oral.id)
            .order_by(OralTestQuestion.question_order.asc())
            .all()
        )
        if retry_rows:
            return [row.question_text for row in retry_rows], "database"
        raise

    logger.warning(
        "oral_questions: fallback d'urgence — test_oral_id=%s, %s question(s)",
        oral.id,
        len(texts),
    )
    return texts, "emergency_fallback"
