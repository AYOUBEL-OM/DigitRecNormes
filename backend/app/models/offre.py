from sqlalchemy import Column, Text, Integer, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class Offre(Base):
    __tablename__ = "offres"

    id = Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Mapping to the actual database column 'id_entreprise'
    entreprise_id = Column(
        "id_entreprise",
        UUID(as_uuid=True),
        ForeignKey("entreprises.id"),
        nullable=True,
    )

    title = Column("title", Text, nullable=True)
    profile = Column("profile", Text, nullable=True)
    nombre_candidats_recherche = Column("nombre_candidats_recherche", Integer, nullable=True)
    type_examens_ecrit = Column("type_examens_ecrit", Text, nullable=True)
    nombre_questions_orale = Column("nombre_questions_orale", Integer, nullable=True)
    date_fin_offres = Column("date_fin_offres", DateTime(timezone=True), nullable=True)
    nombre_experience_minimun = Column("nombre_experience_minimun", Integer, nullable=True)
    description_postes = Column("description_postes", Text, nullable=True)
    token_liens = Column("token_liens", Text, unique=True, default=lambda: str(uuid.uuid4()))
    status = Column("status", Text, default="active")
    type_contrat = Column("type_contrat", Text, nullable=True)
    localisation = Column("localisation", Text, nullable=True)

    # Colonne PG : identifiant "Compétences requises" (guillemets). Sans `key="competences"`,
    # SQLAlchemy utilise le nom SQL comme clé dans Table.c et l’hydratation vers l’attribut
    # Python `competences` ne reçoit pas la valeur (reste None).
    competences = Column(
        "Compétences requises",
        Text,
        nullable=True,
        quote=True,
        key="competences",
    )

    # Niveau d’expérience requis (Junior / Confirmé / Senior) — colonne distincte de `niveau_etude`.
    level = Column("level", Text, nullable=True)
    niveau_etude = Column("niveau_etude", Text, nullable=True)

    created_at = Column("created_at", DateTime(timezone=True), default=datetime.utcnow)

    entreprise = relationship("Entreprise", back_populates="offres")
    candidatures = relationship(
        "Candidature",
        back_populates="offre",
        cascade="all, delete-orphan",
    )