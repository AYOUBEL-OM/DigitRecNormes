"""
Sécurité : hash des mots de passe et JWT.
On utilise bcrypt directement avec au plus 72 octets pour éviter toute erreur passlib.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from app.config import get_settings

settings = get_settings()

# Limite bcrypt : 72 octets
BCRYPT_MAX_BYTES = 72


def _to_72_bytes(value: str) -> bytes:
    """Retourne au plus 72 octets UTF-8. Accepte str ou bytes."""
    if isinstance(value, bytes):
        return value[:BCRYPT_MAX_BYTES]
    return value.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hasher_mot_de_passe(mot_de_passe: str) -> str:
    raw = _to_72_bytes(str(mot_de_passe))
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(raw, salt)
    return hashed.decode("utf-8")


def verifier_mot_de_passe(plain: str, hashed: str) -> bool:
    raw = _to_72_bytes(str(plain))
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except Exception:
        return False


def creer_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    # Use timezone-aware datetime
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decoder_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None