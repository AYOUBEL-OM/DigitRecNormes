"""
Candidatures : dépôt par le candidat et liste par l'entreprise.
"""
import os
import uuid

from fastapi import APIRouter, HTTPException, status, UploadFile, File, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.auth import get_entreprise_from_token, get_candidat_from_token
from app.config import get_settings
from app.database import get_db
from app.models.offre import Offre
from app.models.candidat import Candidat
from app.models.candidature import Candidature, StatutCandidature
from app.services.cv_filtering import run_cv_filtering_for_candidature

router = APIRouter(prefix="/candidatures", tags=["Candidatures"])
settings = get_settings()


def _allowed_extension(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in settings.ALLOWED_CV_EXTENSIONS.split(",")


@router.post("/offre/{token}", status_code=status.HTTP_201_CREATED)
def soumettre_candidature(
    token: str,
    background_tasks: BackgroundTasks,
    cv: UploadFile = File(...),
    candidat: Candidat = Depends(get_candidat_from_token),
    db: Session = Depends(get_db),
):
    offre = (
        db.query(Offre)
        .filter(Offre.token_liens == token, Offre.status == "active")
        .first()
    )

    if not offre:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offre introuvable ou inactive.",
        )

    if not cv.filename or not _allowed_extension(cv.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Format de CV non autorisé. Autorisés : {settings.ALLOWED_CV_EXTENSIONS}",
        )

    existing = (
        db.query(Candidature)
        .filter(
            Candidature.candidat_id == candidat.id,
            Candidature.offre_id == offre.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous avez déjà soumis une candidature pour cette offre.",
        )

    content = cv.file.read()
    max_bytes = settings.MAX_CV_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le CV dépasse la taille maximale ({settings.MAX_CV_SIZE_MB} Mo).",
        )

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = (cv.filename or "pdf").rsplit(".", 1)[-1].lower()
    unique_name = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(content)

    new_candidature = Candidature(
        candidat_id=candidat.id,
        offre_id=offre.id,
        cv_path=f"/uploads/cv/{unique_name}",
        statut=StatutCandidature.nouvelle,
    )
    db.add(new_candidature)
    db.commit()
    db.refresh(new_candidature)

    background_tasks.add_task(
        run_cv_filtering_for_candidature,
        candidature_id=new_candidature.id,
        offre_id=offre.id,
        cv_abs_path=os.path.abspath(file_path),
    )

    return {
        "id": str(new_candidature.id),
        "candidat_id": str(new_candidature.candidat_id),
        "offre_id": str(new_candidature.offre_id),
        "cv_path": new_candidature.cv_path,
        "statut": new_candidature.statut.value,
        "created_at": new_candidature.created_at.isoformat() if new_candidature.created_at else None,
    }


@router.get("")
def lister_candidatures_entreprise(
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    offre_ids = [
        offre.id
        for offre in db.query(Offre).filter(Offre.entreprise_id == entreprise.id).all()
    ]

    if not offre_ids:
        return []

    candidatures = (
        db.query(Candidature)
        .filter(Candidature.offre_id.in_(offre_ids))
        .order_by(Candidature.created_at.desc())
        .all()
    )

    result = []
    for c in candidatures:
        candidat = db.query(Candidat).filter(Candidat.id == c.candidat_id).first()
        offre = db.query(Offre).filter(Offre.id == c.offre_id).first()

        result.append(
            {
                "id": str(c.id),
                "candidat_id": str(c.candidat_id),
                "offre_id": str(c.offre_id),
                "cv_path": c.cv_path,
                "statut": c.statut.value if c.statut else "nouvelle",
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "candidat_nom": candidat.nom if candidat else None,
                "candidat_prenom": candidat.prenom if candidat else None,
                "candidat_email": candidat.email if candidat else None,
                "offre_titre": offre.title if offre else None,
            }
        )

    return result