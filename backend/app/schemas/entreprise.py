"""
Schémas Pydantic pour Entreprise.
"""
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class EntrepriseBase(BaseModel):
    email_prof: EmailStr
    nom: str = Field(..., min_length=1, max_length=255)

    class Config:
        populate_by_name = True


class EntrepriseCreate(EntrepriseBase):
    mot_de_passe: str = Field(..., min_length=8, max_length=72)  # ✅ 72 وليس 128


class EntrepriseUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    mot_de_passe: Optional[str] = Field(None, min_length=8, max_length=72)  # ✅ 72


class EntrepriseMePatch(BaseModel):
    """Mise à jour partielle du profil entreprise (authentifié)."""

    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=10_000)


class EntrepriseChangePassword(BaseModel):
    ancien_mot_de_passe: str = Field(..., min_length=1, max_length=128)
    nouveau_mot_de_passe: str = Field(..., min_length=8, max_length=72)


class EntrepriseLogin(BaseModel):
    email_prof: EmailStr
    mot_de_passe: str


class EntrepriseResponse(EntrepriseBase):
    id: str  # ✅ UUID (string) وليس int
    created_at: datetime

    class Config:
        from_attributes = True


class TokenData(BaseModel):
    id: str
    email: str