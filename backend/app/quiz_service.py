import uuid
import logging
from sqlalchemy.orm import Session
from app.models.offre import Offre

logger = logging.getLogger(__name__)

def get_quiz_config(db: Session, offre_id: str):
    """
    Récupère la configuration de l'offre pour le quiz.
    Sécurise la conversion UUID pour éviter les DATABASE_QUERY_ERROR.
    """
    try:
        # Validation et conversion explicite en objet UUID.
        # Si la chaîne n'est pas un UUID valide, on intercepte l'erreur ici
        # plutôt que de laisser la requête SQL échouer (évite le ROLLBACK).
        if isinstance(offre_id, str):
            target_id = uuid.UUID(offre_id)
        else:
            target_id = offre_id
    except (ValueError, AttributeError) as e:
        logger.error(f"Format UUID invalide pour offre_id: {offre_id} - {e}")
        return None

    try:
        # La requête utilise maintenant un objet UUID, ce qui permet à SQLAlchemy
        # de générer le SQL correct (ex: WHERE id = '...'::uuid)
        offre = db.query(Offre).filter(Offre.id == target_id).first()
        
        if not offre:
            logger.warning(f"Offre introuvable en base pour l'ID: {target_id}")
            return None
            
        return offre
    except Exception as e:
        logger.error(f"DATABASE_QUERY_ERROR lors de la récupération du quiz: {e}")
        db.rollback()  # Nettoyage de la transaction suite à l'erreur
        return None