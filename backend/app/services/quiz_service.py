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
        
        Format JSON STRICT :
        {{
            "EXERCICE": {{
                "title": "Titre de l'exercice",
                "description": "Scénario détaillé + la question précise",
                "initial_code": "// Votre code ici"
            }}
        }}
        """
    else:
        prompt = f"""
        Génère un QCM technique (30 questions) pour {config['title']} ({config['level']}).
        Format JSON STRICT :
        {{
            "questions": [
                {{"question": "Texte", "options": ["A", "B", "C", "D"], "answer": "A"}}
            ]
        }}
        """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Assistant de recrutement. Réponse en JSON uniquement."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        result = json.loads(completion.choices[0].message.content)
        return {**result, "quiz_type": config['quiz_type'], "title": config['title']}
    except Exception as e:
        logger.error(f"Groq Error: {str(e)}")
        raise ValueError(f"Erreur Groq: {str(e)}")

def evaluate_submission(code: str, consigne: str) -> dict[str, Any]:
    prompt = (
        f"Évalue la réponse suivante pour la consigne: {consigne}\n"
        f"Réponse: {code}\n"
        f"Renvoie un score sur 100 et un feedback court en JSON: {{'score': 0, 'feedback': '...'}}"
    )
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "feedback": "Erreur lors de l'évaluation technique."}