"""
Schémas Pydantic pour Candidature.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class StatutCandidatureEnum(str, Enum):
    nouvelle = "nouvelle"
    en_cours = "en_cours"
    acceptee = "acceptee"
    refusee = "refusee"


class CandidatureBase(BaseModel):
    statut: StatutCandidatureEnum = StatutCandidatureEnum.nouvelle


class CandidatureCreate(BaseModel):
    """Création après upload du CV (cv_path fourni par le backend)."""
    pass


class CandidatureUpdate(BaseModel):
    statut: Optional[StatutCandidatureEnum] = None


class CandidatureResponse(CandidatureBase):
    id: int
    candidat_id: str
    offre_id: int
    cv_path: str
    created_at: datetime

    class Config:
        from_attributes = True


class CandidatureResponseDetail(CandidatureResponse):
    """Avec infos candidat et offre pour le dashboard."""
    candidat_nom: str = ""
    candidat_prenom: str = ""
    candidat_email: str = ""
    offre_titre: str = ""

    class Config:
        from_attributes = True
