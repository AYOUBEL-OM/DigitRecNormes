from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import creer_access_token, hasher_mot_de_passe, verifier_mot_de_passe
from app.database import get_db
from app.models.entreprise import Entreprise
from app.schemas.entreprise import EntrepriseCreate, EntrepriseLogin
 
router = APIRouter()
settings = get_settings()
 
@router.post("/auth/entreprise/inscription", status_code=status.HTTP_201_CREATED)
def register(data: EntrepriseCreate, db: Session = Depends(get_db)):
    try:
        existing = db.query(Entreprise).filter(Entreprise.email_prof == data.email_prof).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
       
        new_entreprise = Entreprise(
            email_prof=data.email_prof,
            nom=data.nom,
            mot_de_passe_hash=hasher_mot_de_passe(data.mot_de_passe)
        )
        db.add(new_entreprise)
        db.commit()
        db.refresh(new_entreprise)
 
        return {"message": "Inscription réussie", "id": str(new_entreprise.id)}
       
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")
 
@router.post("/auth/entreprise/login")
def login(data: EntrepriseLogin, db: Session = Depends(get_db)):
    try:
        # Même adresse que saisie manuelle / gestionnaire : comparaison insensible à la casse + espaces.
        email_norm = str(data.email_prof).strip().lower()
        user = (
            db.query(Entreprise)
            .filter(func.lower(Entreprise.email_prof) == email_norm)
            .first()
        )
       
        if not user:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
       
        if not verifier_mot_de_passe(data.mot_de_passe, user.mot_de_passe_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
       
        token = creer_access_token(
            data={"sub": str(user.id), "email": user.email_prof, "type": "entreprise"},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
       
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email_prof,
                "type": "entreprise"
            }
        }
       
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")