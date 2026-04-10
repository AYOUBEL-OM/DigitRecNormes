"""
Schémas Pydantic pour la validation et la sérialisation.
"""
from app.schemas.entreprise import (
    EntrepriseCreate,
    EntrepriseUpdate,
    EntrepriseResponse,
    EntrepriseLogin,
)
from app.schemas.offre import (
    OffreCreate,
    OffreUpdate,
    OffreResponse,
    OffreResponseAvecLien,
)
from app.schemas.candidat import (
    CandidatCreate,
    CandidatUpdate,
    CandidatResponse,
    CandidatLogin,
)
from app.schemas.candidature import (
    CandidatureCreate,
    CandidatureUpdate,
    CandidatureResponse,
    StatutCandidatureEnum,
)

__all__ = [
    "EntrepriseCreate",
    "EntrepriseUpdate",
    "EntrepriseResponse",
    "EntrepriseLogin",
    "OffreCreate",
    "OffreUpdate",
    "OffreResponse",
    "OffreResponseAvecLien",
    "CandidatCreate",
    "CandidatUpdate",
    "CandidatResponse",
    "CandidatLogin",
    "CandidatureCreate",
    "CandidatureUpdate",
    "CandidatureResponse",
    "StatutCandidatureEnum",
]