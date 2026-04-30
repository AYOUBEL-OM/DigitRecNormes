import json
import logging
import os
import time
from typing import Any

from groq import APIError, Groq, RateLimitError
from sqlalchemy import cast, String as SQLString, or_
import uuid
from sqlalchemy.orm import Session
from app.models.offre import Offre
from app.services.morocco_text_pipeline import (
    apply_pipeline_to_quiz_payload,
    run_morocco_pipeline,
)

logger = logging.getLogger(__name__)
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Réponse publique candidat : jamais le code « solution » du LLM (souvent renseigné dans initial_code).
_CANDIDATE_EXERCICE_EDITOR_STUB = "# Saisissez votre réponse ci-dessous.\n"

_EXERCICE_LEAK_KEYS = frozenset(
    {
        "solution",
        "corrige",
        "correction",
        "correction_attendue",
        "reference_solution",
        "expected_solution",
        "modele_reponse",
        "reponse_attendue",
        "answer_key",
    }
)


def sanitize_exercice_payload_for_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Retire tout champ de correction et remplace initial_code par un stub neutre.
    Le modèle peut renvoyer une solution complète dans initial_code — ne jamais la renvoyer au client.
    """
    out = dict(payload)

    def _clean_block(block: dict[str, Any]) -> dict[str, Any]:
        cleaned = {k: v for k, v in block.items() if k not in _EXERCICE_LEAK_KEYS}
        cleaned["initial_code"] = _CANDIDATE_EXERCICE_EDITOR_STUB
        return cleaned

    for key in ("EXERCICE", "exercice"):
        sub = out.get(key)
        if isinstance(sub, dict):
            out[key] = _clean_block(sub)
    return out

PRIMARY_GROQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_GROQ_MODEL = "llama3-8b-8192"


class EvaluationTechnicalFailure(Exception):
    """
    Échec technique (API LLM, JSON invalide, réponse incomplète) — à ne pas confondre avec un score 0 légitime.
    """


def _groq_chat_json_completion(messages: list[dict[str, str]]) -> Any:
    """
    Appel Groq en JSON mode : sur quota (429), bascule vers un modèle léger puis une 2e tentative après 3 s.
    """
    last_rl: RateLimitError | None = None
    for attempt in range(2):
        if attempt:
            time.sleep(3)
        try:
            return client.chat.completions.create(
                model=PRIMARY_GROQ_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except RateLimitError as e:
            last_rl = e
            logger.warning(
                "Groq RateLimitError sur modèle principal (tentative %s): %s",
                attempt,
                e,
            )
            try:
                return client.chat.completions.create(
                    model=FALLBACK_GROQ_MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
            except RateLimitError as e2:
                last_rl = e2
                logger.warning(
                    "Groq RateLimitError sur modèle de secours (tentative %s): %s",
                    attempt,
                    e2,
                )
                continue
        except APIError as e:
            logger.exception("Groq APIError (hors quota)")
            raise EvaluationTechnicalFailure("GENERIC_ERROR") from e
    raise EvaluationTechnicalFailure("RATE_LIMIT") from last_rl


def _coerce_eval_score(raw: dict[str, Any]) -> float:
    s = raw.get("score")
    if s is None:
        raise EvaluationTechnicalFailure("Réponse évaluateur sans champ « score ».")
    try:
        v = float(s)
    except (TypeError, ValueError) as e:
        raise EvaluationTechnicalFailure("Score non numérique dans la réponse évaluateur.") from e
    return max(0.0, min(100.0, v))

# --- Contexte Maroc (tests écrits : QCM / exercices) — monnaie, fiscalité, cadre économique ---
_SYSTEM_RECRUITMENT_MOROCCO = """Tu es un assistant de recrutement pour le marché du travail au Maroc.

Règles OBLIGATOIRES pour tout contenu produit (énoncés, scénarios, propositions de réponses, chiffres) :
- Monnaie : utiliser exclusivement le dirham marocain (DH ou MAD). Ne jamais utiliser le symbole €, ni EUR, ni £ ; éviter le dollar sauf cas d’import/export explicitement nécessaire.
- Montants : ordres de grandeur crédibles pour une PME ou une société marocaine (ex. milliers à millions de DH).
- Fiscalité : IS (Impôt sur les sociétés) ; TVA marocaine (taux standard couramment 20 % ; citer un taux réduit seulement si le cas l’exige).
- Cadre géographique et économique : entreprises, filiales ou PME implantées au Maroc ; villes possibles : Casablanca, Rabat, Tanger, Marrakech, Fès, Agadir ; fournisseurs, clients ou banques dans un contexte marocain ou maghrébin lorsque pertinent.
- Vocabulaire : français professionnel ; ne pas présenter par défaut le droit fiscal ou social français ou européen comme cadre principal.

Réponds strictement au format JSON demandé par l’utilisateur, sans texte hors JSON."""

_USER_SUFFIX_MOROCCO = """
Contraintes supplémentaires : ancrer le contenu dans le contexte professionnel marocain (DH/MAD, IS, TVA si chiffres ou fiscalité). Aucune devise € dans les énoncés."""

def get_quiz_config(db: Session, offre_id: Any) -> dict[str, Any]:
    """
    Fetch quiz configuration. 
    كتحافظ على نفس اللوجيك اللي خدم لينا باش نتفاداو OFFRE_NOT_FOUND
    """
    if hasattr(offre_id, 'id'):
        target_id_str = str(offre_id.id).strip()
    else:
        target_id_str = str(offre_id).strip() if offre_id else ""

    try:
        offre = db.query(Offre).filter(
            or_(
                cast(Offre.id, SQLString) == target_id_str,
                Offre.token_liens == target_id_str
            )
        ).first()

        if not offre:
            raise ValueError("OFFRE_NOT_FOUND")
        
        raw_type = offre.type_examens_ecrit
        quiz_type = raw_type.strip().lower() if raw_type else "qcm"
        
        return {
            "offre_id": str(offre.id),
            "title": offre.title or "Poste inconnu",
            "level": offre.level or "Bac+5",
            "quiz_type": quiz_type,
            "description": offre.description_postes or "",
            "competences": offre.competences or ""
        }
    except Exception as e:
        if str(e) != "OFFRE_NOT_FOUND":
            db.rollback()
        raise

def generate_quiz_content(db: Session, offre_id: Any) -> dict[str, Any]:
    # كنستعملوا config اللي جاية من الدالة اللي الفوق
    config = get_quiz_config(db, offre_id)
    
    # اختيار الـ Prompt على حساب نوع الامتحان
    if "exercice" in config['quiz_type']:
        prompt = f"""
        Tu es un recruteur expert en {config['title']}.
        Génère un exercice pratique détaillé pour un candidat niveau {config['level']}.
        Détails du poste : {config['description']}
        Compétences visées : {config['competences']}

        Le scénario doit être plausible pour une société ou une PME marocaine (ville, secteur, montants en DH si des chiffres apparaissent).
        Si l’exercice touche à la finance ou à la fiscalité : mentionner IS et TVA marocaine avec des taux réalistes (ex. TVA 20 %, IS selon le cas entre ~20 % et ~30 % pour une illustration professionnelle, sans substitut au conseil juridique).

        Format JSON STRICT :
        {{
            "EXERCICE": {{
                "title": "Titre de l'exercice",
                "description": "Scénario détaillé + la question précise",
                "initial_code": "// Votre code ici"
            }}
        }}
        {_USER_SUFFIX_MOROCCO}
        """
    else:
        prompt = f"""
        Génère un QCM technique (30 questions) pour {config['title']} ({config['level']}).
        Contexte du poste : {config['description']}
        Compétences : {config['competences']}

        Chaque question doit pouvoir s’appliquer au contexte professionnel marocain (entreprise marocaine, normes ou pratiques courantes au Maroc lorsque le sujet s’y prête).
        Toute somme d’argent doit être exprimée en DH (MAD), jamais en €.

        Format JSON STRICT :
        {{
            "questions": [
                {{"question": "Texte", "options": ["A", "B", "C", "D"], "answer": "A"}}
            ]
        }}
        {_USER_SUFFIX_MOROCCO}
        """
    
    messages = [
        {"role": "system", "content": _SYSTEM_RECRUITMENT_MOROCCO},
        {"role": "user", "content": prompt},
    ]
    try:
        completion = _groq_chat_json_completion(messages)
        content = completion.choices[0].message.content
        if not content or not str(content).strip():
            raise EvaluationTechnicalFailure("GENERIC_ERROR")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            logger.exception("generate_quiz_content: JSON LLM invalide")
            raise EvaluationTechnicalFailure("GENERIC_ERROR") from e
        result = apply_pipeline_to_quiz_payload(result)
        qt = str(config.get("quiz_type") or "").lower()
        if "exercice" in qt:
            result = sanitize_exercice_payload_for_candidate(result)
        return {**result, "quiz_type": config['quiz_type'], "title": config['title']}
    except EvaluationTechnicalFailure:
        raise
    except ValueError:
        raise
    except Exception as e:
        logger.exception("generate_quiz_content: erreur inattendue")
        raise EvaluationTechnicalFailure("GENERIC_ERROR") from e

def evaluate_submission(code: str, consigne: str) -> dict[str, Any]:
    prompt = (
        f"Évalue la réponse suivante pour la consigne (recrutement au Maroc, cadre professionnel marocain si le sujet le permet) :\n"
        f"Consigne : {consigne}\n"
        f"Réponse du candidat : {code}\n"
        f"Renvoie un score sur 100 et un feedback court en français professionnel, au format JSON strict : "
        f"{{\"score\": 0, \"feedback\": \"...\"}}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_RECRUITMENT_MOROCCO},
        {"role": "user", "content": prompt},
    ]
    try:
        completion = _groq_chat_json_completion(messages)
        content = completion.choices[0].message.content
        if not content or not str(content).strip():
            raise EvaluationTechnicalFailure("Réponse LLM vide.")
        try:
            parsed: Any = json.loads(content)
        except json.JSONDecodeError as e:
            raise EvaluationTechnicalFailure("Réponse évaluateur : JSON invalide.") from e
        if not isinstance(parsed, dict):
            raise EvaluationTechnicalFailure("Réponse évaluateur : objet JSON attendu.")
        raw = parsed
        raw["score"] = _coerce_eval_score(raw)
        fb = raw.get("feedback")
        if isinstance(fb, str):
            raw["feedback"], _ = run_morocco_pipeline(fb, mode="prose")
        elif fb is not None:
            raw["feedback"] = str(fb)
        raw["evaluation_ok"] = True
        return raw
    except ValueError:
        logger.warning("evaluate_submission: validation devise Maroc — rejet du contenu LLM")
        raise
    except EvaluationTechnicalFailure:
        raise
    except Exception as e:
        logger.exception("evaluate_submission: erreur Groq ou traitement de la réponse")
        raise EvaluationTechnicalFailure("Évaluation technique indisponible.") from e