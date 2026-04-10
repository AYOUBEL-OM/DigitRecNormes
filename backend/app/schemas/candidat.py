from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from typing import Optional


class CandidatBase(BaseModel):
    email: EmailStr
    nom: str = Field(..., min_length=1, max_length=255)
    prenom: str = Field(..., min_length=1, max_length=255)


class CandidatCreate(CandidatBase):
    mot_de_passe: str = Field(..., min_length=8, max_length=72)
    cin: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    profile: str = Field(..., min_length=1, max_length=255)
    level: str = Field(..., min_length=1, max_length=255)


class CandidatUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    prenom: Optional[str] = Field(None, min_length=1, max_length=255)
    mot_de_passe: Optional[str] = Field(None, min_length=8, max_length=72)


class CandidatLogin(BaseModel):
    email: EmailStr
    mot_de_passe: str


class CandidatResponse(CandidatBase):
    id: UUID
    created_at: datetime
    cin: Optional[str] = None
    cv_url: Optional[str] = None
    title: Optional[str] = None
    profile: Optional[str] = None
    level: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)