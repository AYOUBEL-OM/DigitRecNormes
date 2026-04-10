"""
Modèle Candidat.
"""
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base


class Candidat(Base):
    __tablename__ = "candidats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email = Column(String(255), unique=True, nullable=False, index=True)
    mot_de_passe_hash = Column(String(255), nullable=False)

    nom = Column(String(255), nullable=False)
    prenom = Column(String(255), nullable=False)

    cin = Column(Text, nullable=True)
    cv_url = Column(Text, nullable=True)
    title = Column(String(255), nullable=True)
    profile = Column(String(255), nullable=True)
    level = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    candidatures = relationship(
        "Candidature",
        back_populates="candidat",
        cascade="all, delete-orphan"
    )