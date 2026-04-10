"""
Inscription et connexion des candidats.
"""
import os
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, File, Form, UploadFile
from pydantic import ValidationError
from app.schemas.candidat import CandidatCreate, CandidatLogin, CandidatResponse
from app.core.security import hasher_mot_de_passe, verifier_mot_de_passe, creer_access_token
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.candidat import Candidat
from app.config import get_settings

router = APIRouter(prefix="/auth/candidat", tags=["Auth Candidat"])
settings = get_settings()


def _allowed_cv_extension(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in settings.ALLOWED_CV_EXTENSIONS.split(",")


@router.post("/inscription", response_model=CandidatResponse, status_code=status.HTTP_201_CREATED)
def inscription_candidat(
    email: str = Form(...),
    nom: str = Form(...),
    prenom: str = Form(...),
    mot_de_passe: str = Form(...),
    cin: str = Form(...),
    title: str = Form(...),
    profile: str = Form(...),
    level: str = Form(...),
    cv: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    try:
        try:
            data = CandidatCreate(
                email=email.strip(),
                nom=nom.strip(),
                prenom=prenom.strip(),
                mot_de_passe=mot_de_passe,
                cin=cin.strip(),
                title=title.strip(),
                profile=profile.strip(),
                level=level.strip(),
            )
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            )

        existing = db.query(Candidat).filter(Candidat.email == str(data.email)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un candidat avec cet email existe déjà.",
            )

        cv_url_value = None
        if cv and cv.filename:
            content = cv.file.read()
            max_bytes = settings.MAX_CV_SIZE_MB * 1024 * 1024
            if len(content) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Le CV dépasse la taille maximale ({settings.MAX_CV_SIZE_MB} Mo).",
                )
            if not _allowed_cv_extension(cv.filename):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Format de CV non autorisé. Autorisés : {settings.ALLOWED_CV_EXTENSIONS}",
                )
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
            ext = (cv.filename or "pdf").rsplit(".", 1)[-1].lower()
            unique_name = f"{uuid.uuid4()}.{ext}"
            file_path = os.path.join(settings.UPLOAD_DIR, unique_name)
            with open(file_path, "wb") as f:
                f.write(content)
            cv_url_value = f"/uploads/cv/{unique_name}"

        new_candidat = Candidat(
            email=str(data.email),
            mot_de_passe_hash=hasher_mot_de_passe(data.mot_de_passe),
            nom=data.nom,
            prenom=data.prenom,
            cin=data.cin,
            title=data.title,
            profile=data.profile,
            level=data.level,
            cv_url=cv_url_value,
        )
        db.add(new_candidat)
        db.commit()
        db.refresh(new_candidat)

        return CandidatResponse.model_validate(new_candidat)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur serveur: {str(e)}",
        )


@router.post("/login")
def login_candidat(data: CandidatLogin, db: Session = Depends(get_db)):
    try:
        # Search candidate by email
        candidat = db.query(Candidat).filter(Candidat.email == data.email).first()

        if not candidat:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect.",
            )

        # Verify password
        if not verifier_mot_de_passe(data.mot_de_passe, candidat.mot_de_passe_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect.",
            )

        # Generate JWT Token
        token = creer_access_token(data={"sub": str(candidat.id), "email": candidat.email, "type": "candidat"})

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": str(candidat.id),
                "email": candidat.email,
                "type": "candidat",
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur serveur: {str(e)}",
        )
