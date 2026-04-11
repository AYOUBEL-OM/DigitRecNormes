from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import quiz_service
from app.models.offre import Offre

router = APIRouter(tags=["quiz"])

class EvaluateBody(BaseModel):
    code: str = Field(..., description="Réponse du candidat (code ou texte)")
    consigne: str = Field(..., description="Consigne / description de l'exercice")

@router.get("/quiz/config/{identifier}")
async def quiz_config(identifier: UUID, db: Session = Depends(get_db)):
    """
    Vérifie l'ID de l'offre et renvoie la config.
    """
    offre = db.query(Offre).filter(Offre.id == identifier).first()
    if not offre:
        raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

    try:
        # هنا كنصيفطو الـ Offre Object كامل باش الـ service يخدم مرتاح
        return quiz_service.get_quiz_config(db, offre)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/generate/{identifier}")
async def generate_quiz(identifier: UUID, db: Session = Depends(get_db)):
    """
    Génère le quiz en utilisant l'ID de l'offre.
    """
    offre = db.query(Offre).filter(Offre.id == identifier).first()
    if not offre:
        raise HTTPException(status_code=404, detail="OFFRE_NOT_FOUND")

    try:
        return quiz_service.generate_quiz_content(db, offre)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluate")
async def evaluate(body: EvaluateBody):
    try:
        return quiz_service.evaluate_submission(body.code, body.consigne)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Evaluation failed")