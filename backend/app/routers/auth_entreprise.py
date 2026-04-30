from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import creer_access_token, hasher_mot_de_passe, verifier_mot_de_passe
from app.database import get_db
from app.models.entreprise import Entreprise
from app.models.password_reset_token import PasswordResetToken
from app.models.subscription import Subscription
from app.schemas.entreprise import EntrepriseCreate, EntrepriseLogin
from app.schemas.password_reset import ForgotPasswordRequest, ResetPasswordRequest
from app.services.email_service import send_password_reset_email
from app.services.subscription_access import ensure_default_trial_subscription

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
        db.flush()

        trial = Subscription(
            entreprise_id=new_entreprise.id,
            plan_code="TRIAL",
            billing_cycle="free",
            status="active",
            currency="mad",
        )
        db.add(trial)
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

        ensure_default_trial_subscription(db, user.id)

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
                "email_prof": user.email_prof,
                "nom": user.nom,
                "description": getattr(user, "description", None),
                "type": "entreprise",
            },
        }
       
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


def _token_hmac_sha256_hex(raw_token: str) -> str:
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    msg = str(raw_token).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


@router.post("/auth/entreprise/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    body: ForgotPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Demande de reset mot de passe (entreprise).
    Ne révèle jamais si l'email existe (anti-énumération).
    """
    email_norm = str(body.email).strip().lower()
    generic = {
        "message": "Si un compte existe avec cet email, un lien de réinitialisation a été envoyé."
    }

    try:
        ent = (
            db.query(Entreprise)
            .filter(func.lower(Entreprise.email_prof) == email_norm)
            .first()
        )
        if not ent:
            return generic

        # Invalider les anciens tokens encore non utilisés (one active token max).
        now = datetime.now(timezone.utc)
        db.query(PasswordResetToken).filter(
            PasswordResetToken.entreprise_id == ent.id,
            PasswordResetToken.used_at.is_(None),
        ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

        raw_token = secrets.token_urlsafe(48)
        token_hash = _token_hmac_sha256_hex(raw_token)
        expires_at = now + timedelta(minutes=30)

        row = PasswordResetToken(
            entreprise_id=ent.id,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None,
        )
        db.add(row)
        db.commit()

        base = (settings.FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
        safe_token = quote(raw_token.strip(), safe="")
        reset_url = f"{base}/reset-password?token={safe_token}"

        # Email en arrière-plan (ne pas loguer le token complet).
        background.add_task(send_password_reset_email, ent.email_prof, reset_url)
        return generic
    except Exception:
        # Anti-énumération : même réponse 200.
        return generic


@router.post("/auth/entreprise/reset-password", status_code=status.HTTP_200_OK)
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    token_raw = str(body.token or "").strip()
    if not token_raw:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré.")

    token_hash = _token_hmac_sha256_hex(token_raw)
    row = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Token invalide ou expiré.")

    ent = db.query(Entreprise).filter(Entreprise.id == row.entreprise_id).first()
    if not ent:
        # Cas très rare : entreprise supprimée.
        row.used_at = now
        db.add(row)
        db.commit()
        raise HTTPException(status_code=400, detail="Token invalide ou expiré.")

    ent.mot_de_passe_hash = hasher_mot_de_passe(body.new_password)
    row.used_at = now
    db.add(ent)
    db.add(row)
    db.commit()
    return {"message": "Votre mot de passe a été réinitialisé avec succès."}