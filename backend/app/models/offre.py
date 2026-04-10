from sqlalchemy import Column, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class Offre(Base):
    __tablename__ = "offres"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entreprise_id = Column(
        "id_entreprise",
        UUID(as_uuid=True),
        ForeignKey("entreprises.id", ondelete="CASCADE"),
        nullable=True,
    )

    title = Column(Text, nullable=True)
    profile = Column(Text, nullable=True)
    level = Column(Text, nullable=True)
    nombre_candidats_recherche = Column(Integer, nullable=True)
    type_examens_ecrit = Column(Text, nullable=True)
    nombre_questions_orale = Column(Integer, nullable=True)
    date_fin_offres = Column(DateTime(timezone=True), nullable=True)
    nombre_experience_minimun = Column(Integer, nullable=True)
    description_postes = Column(Text, nullable=True)
    token_liens = Column(Text, unique=True, default=lambda: str(uuid.uuid4()))
    status = Column(Text, default="active")
    type_contrat = Column(Text, nullable=True)
    localisation = Column(Text, nullable=True)
    competences = Column("Compétences requises", Text, nullable=True)
    niveau_etude = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    entreprise = relationship("Entreprise", back_populates="offres")
    candidatures = relationship(
        "Candidature",
        back_populates="offre",
        cascade="all, delete-orphan",
    )