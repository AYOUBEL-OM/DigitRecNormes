import json
import os
from typing import Any
from groq import Groq
from sqlalchemy import text
from sqlalchemy.orm import Session

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_quiz_config(db: Session, offre_id: Any) -> dict[str, Any]:
    try:
        # استعملنا Raw SQL باش نتفاداو أي مشكل فـ الـ Mapping ديال SQLAlchemy
        # وجلبنا الحقول اللي عندك فـ الـ Schema بالضبط
        query = text("""
            SELECT id, title, level, niveau_etude, type_examens_ecrit 
            FROM public.offres 
            WHERE id = :oid
        """)
        result = db.execute(query, {"oid": str(offre_id)}).fetchone()
        
        if not result:
            raise ValueError("OFFRE_NOT_FOUND")
        
        # تحويل النتيجة لـ Dictionary باش يسهل التعامل معاها
        # لاحظ أننا خدينا level أو niveau_etude حسب اللي عامر
        raw_type = result.type_examens_ecrit
        quiz_type = raw_type.strip().lower() if raw_type else "qcm"
        
        return {
            "offre_id": str(result.id),
            "title": result.title or "Poste inconnu",
            "level": result.level or result.niveau_etude or "intermédiaire",
            "quiz_type": quiz_type
        }
        
    except Exception as e:
        if "OFFRE_NOT_FOUND" in str(e):
            raise e
        print(f"DEBUG SQL ERROR: {str(e)}")
        raise ValueError("DATABASE_QUERY_ERROR")

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