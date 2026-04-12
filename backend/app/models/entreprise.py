from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Entreprise(Base):
    __tablename__ = "entreprises"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email_prof = Column(String(255), unique=True, nullable=False, index=True)
    mot_de_passe_hash = Column(String(255), nullable=False)
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relation avec Offre
    offres = relationship("Offre", back_populates="entreprise", cascade="all, delete-orphan")