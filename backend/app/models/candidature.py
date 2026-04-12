"""
Modèle Candidature (lien Candidat <-> Offre + CV).
"""
import enum
import uuid

from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, UniqueConstraint, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class StatutCandidature(str, enum.Enum):
    nouvelle = "nouvelle"
    en_cours = "en_cours"
    acceptee = "acceptee"
    refusee = "refusee"


class Candidature(Base):
    __tablename__ = "candidatures"
    __table_args__ = (
        UniqueConstraint("candidat_id", "offre_id", name="uq_candidat_offre"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("candidats.id", ondelete="CASCADE"),
        nullable=False,
    )
    offre_id = Column(
        UUID(as_uuid=True),
        ForeignKey("offres.id", ondelete="CASCADE"),
        nullable=False,
    )
    cv_path = Column(String(512), nullable=False)
    score_cv_matching = Column(Float, nullable=True)
    cv_analysis_report = Column(Text, nullable=True)
    statut = Column(Enum(StatutCandidature), default=StatutCandidature.nouvelle)
    etape_actuelle = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    candidat = relationship("Candidat", back_populates="candidatures")
    offre = relationship("Offre", back_populates="candidatures")