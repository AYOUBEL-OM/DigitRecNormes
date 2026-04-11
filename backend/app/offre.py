from sqlalchemy import Column, String, Integer, Text, ForeignKey, DateTime, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import synonym
from app.database import Base
import uuid

class Offre(Base):
    """
    Modèle SQLAlchemy pour la table 'offres'.
    Gère la conversion automatique UUID et l'unification des champs level/title.
    """
    __tablename__ = "offres"

    # Utilisation du type UUID natif pour assurer la compatibilité Supabase/PostgreSQL
    # as_uuid=True permet à SQLAlchemy de gérer la conversion String <-> UUID automatiquement
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    entreprise_id = Column(Integer, ForeignKey("entreprises.id"), nullable=False)
    
    # Unification des noms de champs : 'title' est utilisé par l'IA et le Frontend, 
    # 'titre' est utilisé par le dashboard.
    title = Column(String, nullable=False)
    @property
    def titre(self):
        return self.title

    profile = Column(String)
    localisation = Column(String)
    type_contrat = Column(String)
    
    # Gestion des critères : On garde les deux pour éviter les erreurs dans cv_filtering
    level = Column(String) 
    niveau_etude = Column(String)
    
    nombre_candidats_recherche = Column(Integer)
    nombre_experience_minimun = Column(Integer)
    competences = Column(Text)
    
    # Configuration Quiz / Évaluation
    type_examens_ecrit = Column(String)
    nombre_questions_orale = Column(Integer)
    date_fin_offres = Column(Date)
    description_postes = Column(Text)
    
    # Token public pour les liens de candidature
    lien_uuid = Column(String, unique=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime(timezone=True), server_default=func.now())