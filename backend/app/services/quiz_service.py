import json
import os
import logging
from typing import Any
from groq import Groq
from sqlalchemy import text, cast, String as SQLString, or_
import uuid
from sqlalchemy.orm import Session
from app.models.offre import Offre

logger = logging.getLogger(__name__)
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_quiz_config(db: Session, offre_id: Any) -> dict[str, Any]:
    """
    Fetch quiz configuration. 
    Handles internal UUIDs and public Tokens to prevent 404.
    """
    # 1. Robust Input Handling
    # If an Offre object was passed, extract its ID. Otherwise, sanitize the input string.
    if hasattr(offre_id, 'id'):
        target_id_str = str(offre_id.id).strip()
    else:
        target_id_str = str(offre_id).strip() if offre_id else ""

    logger.info(f"🔍 Quiz Config Lookup: searching for identifier '{target_id_str}'")

    try:
        # 2. Multi-Strategy Search
        # Using string casting for the ID prevents 'Invalid UUID format' errors in the DB driver
        # and allows checking both the internal ID and the public token_liens in one pass.
        offre = db.query(Offre).filter(
            or_(
                cast(Offre.id, SQLString) == target_id_str,
                Offre.token_liens == target_id_str
            )
        ).first()

        if not offre:
            logger.error(f"❌ OFFRE_NOT_FOUND: Identifier '{target_id_str}' did not match any record.")
            raise ValueError("OFFRE_NOT_FOUND")
        
        logger.info(f"✅ Found Offre: {offre.id} - {offre.title}")
        
        # 3. Configuration Extraction
        raw_type = offre.type_examens_ecrit
        quiz_type = raw_type.strip().lower() if raw_type else "qcm"
        
        return {
            "offre_id": str(offre.id),
            "title": offre.title or "Poste inconnu",
            "level": offre.level or "intermédiaire",  # level is a synonym for niveau_etude in model
            "quiz_type": quiz_type
        }
        
    except Exception as e:
        if str(e) != "OFFRE_NOT_FOUND":
            logger.exception(f"💥 DATABASE_QUERY_ERROR for identifier '{target_id_str}': {str(e)}")
            db.rollback() # Crucial: Clean session state on failure
        raise

def generate_quiz_content(db: Session, offre_id: Any) -> dict[str, Any]:
    # جلب الإعدادات باستعمال الدالة المصلحة
    config = get_quiz_config(db, offre_id)
    
    prompt = f"""
    Génère un QCM technique pour un poste de {config['title']} niveau {config['level']}.
    Génère exactement 10 questions.
    Format JSON strict :
    {{
      "questions": [
        {{
          "question": "Texte de la question",
          "options": ["A", "B", "C", "D"],
          "answer": "La réponse exacte"
        }}
      ]
    }}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(completion.choices[0].message.content)
        return {**result, "quiz_type": config['quiz_type'], "title": config['title']}
    except Exception as e:
        raise ValueError(f"Erreur Groq: {str(e)}")

def evaluate_submission(code: str, consigne: str) -> dict[str, Any]:
    """
    Évalue une réponse libre ou un code via Groq AI.
    """
    prompt = (
        f"Évalue la réponse suivante pour la consigne: {consigne}\n"
        f"Réponse: {code}\n"
        f"Renvoie un score sur 100 et un feedback court en JSON: {{'score': 0, 'feedback': '...'}}"
    )
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Evaluation Error: {str(e)}")
        return {"score": 0, "feedback": "Erreur lors de l'évaluation technique."}