"""
Endpoint Dashboard (données filtrées par entreprise via token JWT).
"""
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_entreprise_from_token
from app.database import get_db
from sqlalchemy.orm import Session
from app.models.offre import Offre
from app.models.candidature import Candidature
from app.models.candidat import Candidat

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("", response_model=dict)
def get_dashboard(
    entreprise: object = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """Retourne les données du dashboard de l'entreprise connectée."""
    
    # 1. Get all offres for this entreprise
    offres = db.query(Offre).filter(Offre.entreprise_id == entreprise.id).order_by(Offre.created_at.desc()).all()
    offres_ids = [o.id for o in offres]
    
    # 2. Get candidatures for these offres
    candidatures = []
    if offres_ids:
        candidatures = (
            db.query(Candidature)
            .filter(Candidature.offre_id.in_(offres_ids))
            .order_by(Candidature.created_at.desc())
            .all()
        )

    # 3. Format response
    candidatures_out = []
    for c in candidatures:
        candidat = db.query(Candidat).get(c.candidat_id)
        candidature_offre = db.query(Offre).get(c.offre_id)

        candidatures_out.append({
            "id": c.id,
            "offre_id": c.offre_id,
            "created_at": c.created_at,
            "etape_actuelle": c.statut.value if c.statut else None,
            "score_cv_matching": None,
            "candidat_nom": candidat.nom if candidat else None,
            "candidat_prenom": candidat.prenom if candidat else None,
            "candidat_email": candidat.email if candidat else None,
        })

    return {
        "id_entreprise": entreprise.id,
        "nom_entreprise": entreprise.nom,
        "email": entreprise.email_prof,
        "offres": [
            {
                "id": o.id,
                "titre": o.titre,
                "lien_uuid": o.lien_uuid,
                "created_at": o.created_at,
            }
            for o in offres
        ],
        "candidatures": candidatures_out,
        "message": f"Dashboard de l'entreprise {entreprise.id}",
    }