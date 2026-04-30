"""
Schémas Pydantic pour le quiz Kandido (vérification candidat, enregistrement du test).
"""
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class QuizVerificationRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    offre_id: UUID


class QuizVerificationResponse(BaseModel):
    id_candidature: UUID


class TestResultCreate(BaseModel):
    id_candidature: UUID
    score_ecrit: float = Field(..., ge=0, le=100)
    detail_snapshot: Optional[dict[str, Any]] = Field(
        default=None,
        description="Détail optionnel (Q/R) pour le rapport entreprise.",
    )


class TestResultResponse(BaseModel):
    id: UUID
    id_candidature: UUID
    score_ecrit: float
    status_reussite: bool
