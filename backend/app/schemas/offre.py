from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID


class OffreCreate(BaseModel):
    title: str
    description_postes: str
    level: str

    profile: Optional[str] = None
    localisation: Optional[str] = None
    type_contrat: Optional[str] = None

    nombre_candidats_recherche: Optional[int] = None
    nombre_experience_minimun: Optional[int] = None
    niveau_etude: Optional[str] = None

    competences: Optional[str] = None

    type_examens_ecrit: Optional[str] = None
    nombre_questions_orale: Optional[int] = None
    date_fin_offres: Optional[datetime] = None


class OffreUpdate(BaseModel):
    title: Optional[str] = None
    description_postes: Optional[str] = None
    level: Optional[str] = None

    profile: Optional[str] = None
    localisation: Optional[str] = None
    type_contrat: Optional[str] = None

    nombre_candidats_recherche: Optional[int] = None
    nombre_experience_minimun: Optional[int] = None
    niveau_etude: Optional[str] = None

    competences: Optional[str] = None

    type_examens_ecrit: Optional[str] = None
    nombre_questions_orale: Optional[int] = None
    date_fin_offres: Optional[datetime] = None
    status: Optional[str] = None


class OffreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: Optional[str] = None
    profile: Optional[str] = None
    localisation: Optional[str] = None
    type_contrat: Optional[str] = None
    level: Optional[str] = None
    nombre_candidats_recherche: Optional[int] = None
    nombre_experience_minimun: Optional[int] = None
    niveau_etude: Optional[str] = None
    competences: Optional[str] = None
    type_examens_ecrit: Optional[str] = None
    nombre_questions_orale: Optional[int] = None
    date_fin_offres: Optional[datetime] = None
    description_postes: Optional[str] = None
    status: Optional[str] = None
    token_liens: Optional[str] = None


class OffreResponseAvecLien(OffreResponse):
    lien_candidature: str


class OffreEntrepriseResponse(OffreResponse):
    """Liste / détail entreprise : lien public, création, état d’accès candidat."""

    created_at: Optional[datetime] = None
    lien_candidature: str = ""
    lien_public_actif: bool = False
    affichage_statut: str = "active"