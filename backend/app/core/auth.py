from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.entreprise import Entreprise
from app.models.candidat import Candidat
from app.core.security import decoder_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/entreprise/login")
http_bearer = HTTPBearer(auto_error=False)


def get_entreprise_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> Entreprise:

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise (entreprise)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decoder_token(credentials.credentials)

    if not payload or payload.get("type") != "entreprise":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
        )

    entreprise_id = payload.get("sub")

    if not entreprise_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide"
        )

    # ✅ هنا الإصلاح: ما كنستعملوش int
    entreprise = db.query(Entreprise).filter(
        Entreprise.id == entreprise_id
    ).first()

    if not entreprise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entreprise introuvable"
        )

    return entreprise


def get_current_entreprise(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.schemas.entreprise import TokenData

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decoder_token(token)

    if not payload or payload.get("type") != "entreprise":
        raise credentials_exception

    id_entreprise = payload.get("sub")
    email = payload.get("email")

    if not id_entreprise or not email:
        raise credentials_exception

    return TokenData(id=id_entreprise, email=email)


def get_candidat_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> Candidat:

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise (candidat)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decoder_token(credentials.credentials)

    if not payload or payload.get("type") != "candidat":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
        )

    candidat_id = payload.get("sub")

    if not candidat_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide"
        )

    # ✅ نفس الإصلاح هنا
    candidat = db.query(Candidat).filter(
        Candidat.id == candidat_id
    ).first()

    if not candidat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidat introuvable"
        )

    return candidat