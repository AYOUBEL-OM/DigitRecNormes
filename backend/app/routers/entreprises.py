"""
Endpoints entreprise authentifiée (JWT).
"""
from pathlib import Path
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from sqlalchemy import desc, func, inspect as sa_inspect, or_, text
from sqlalchemy.orm import Session

from app.core.auth import get_entreprise_from_token
from app.core.security import hasher_mot_de_passe, verifier_mot_de_passe
from app.database import get_db
from app.models.candidat import Candidat
from app.models.candidature import Candidature, StatutCandidature
from app.models.entreprise import Entreprise
from app.models.offre import Offre
from app.schemas.entreprise import EntrepriseChangePassword, EntrepriseMePatch
from app.models.test_ecrit import TestEcrit
from app.models.test_oral import TestOral

router = APIRouter(prefix="/entreprises", tags=["Entreprises"])


def _entreprise_me_dict(ent: Entreprise) -> dict:
    return {
        "id": str(ent.id),
        "nom": ent.nom,
        "email_prof": ent.email_prof,
        "description": ent.description,
    }


@router.get("/me")
def get_me_entreprise(
    entreprise: Entreprise = Depends(get_entreprise_from_token),
) -> dict:
    """Profil entreprise connectée (JWT)."""
    return _entreprise_me_dict(entreprise)


@router.patch("/me")
def patch_me_entreprise(
    data: EntrepriseMePatch,
    entreprise: Entreprise = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict:
    """Met à jour nom et/ou description."""
    if data.nom is not None:
        entreprise.nom = data.nom.strip()
    if data.description is not None:
        entreprise.description = data.description
    db.add(entreprise)
    db.commit()
    db.refresh(entreprise)
    return _entreprise_me_dict(entreprise)


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
def change_password_entreprise(
    data: EntrepriseChangePassword,
    entreprise: Entreprise = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict:
    if not verifier_mot_de_passe(data.ancien_mot_de_passe, entreprise.mot_de_passe_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect",
        )
    entreprise.mot_de_passe_hash = hasher_mot_de_passe(data.nouveau_mot_de_passe)
    db.commit()
    return {"message": "Mot de passe mis à jour"}


def _normalize_score_ia(raw: Any) -> Optional[float]:
    """Mappe score_cv_matching (souvent 0–100) vers une note sur 5."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 5:
        return round(v, 1)
    return round(min(5.0, v / 20.0), 1)


def _read_etape_actuelle(db: Session, candidature_id: UUID) -> Optional[str]:
    """Lit etape_actuelle si la colonne existe (schémas hétérogènes)."""
    bind = db.get_bind()
    if bind is None:
        return None
    try:
        cols = {c["name"] for c in sa_inspect(bind).get_columns("candidatures")}
    except Exception:
        return None
    if "etape_actuelle" not in cols:
        return None
    try:
        return db.execute(
            text("SELECT etape_actuelle FROM candidatures WHERE id = :cid"),
            {"cid": str(candidature_id)},
        ).scalar_one_or_none()
    except Exception:
        return None


def _to_absolute_url(request: Request, raw: Optional[str]) -> Optional[str]:
    """
    Évite les chemins relatifs (/uploads/...) qui s'ouvriraient sur l'origine du frontend (SPA 404).
    """
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    base = str(request.base_url).rstrip("/")
    path = s if s.startswith("/") else f"/{s}"
    return f"{base}{path}"


def _local_upload_file_relative(cv_ref: str) -> Optional[str]:
    """
    Pour /uploads/cv/nom.pdf (ou uploads/cv/...) retourne le chemin relatif sûr sous UPLOAD_DIR.
    """
    s = (cv_ref or "").replace("\\", "/").strip()
    for marker in ("/uploads/cv/", "uploads/cv/"):
        if marker in s:
            rel = s.split(marker, 1)[-1].lstrip("/")
            if rel and ".." not in rel and not rel.startswith("/"):
                return rel
    return None


def _local_cv_file_exists(cv_ref: str) -> bool:
    """True si le fichier existe sur le disque du serveur API (dossier UPLOAD_DIR)."""
    rel = _local_upload_file_relative(cv_ref)
    if not rel:
        return False
    root = Path(get_settings().UPLOAD_DIR).resolve()
    fp = (root / rel).resolve()
    try:
        fp.relative_to(root)
    except ValueError:
        return False
    return fp.is_file()


def _resolve_cv_url(request: Request, candidat: Candidat, candidature: Candidature) -> Optional[str]:
    """
    CV de la candidature (dépôt) prioritaire, puis cv_url du profil candidat.

    Si le chemin en base pointe vers un fichier absent du disque (404 StaticFiles → JSON
    {"detail":"Not Found"} dans le navigateur), on ignore ce chemin et on tente le suivant.
    Les URLs http(s) externes ne sont pas vérifiées ici.
    """
    candidates: List[str] = []
    if candidature.cv_path and str(candidature.cv_path).strip():
        candidates.append(str(candidature.cv_path).strip())
    if candidat.cv_url and str(candidat.cv_url).strip():
        candidates.append(str(candidat.cv_url).strip())

    for raw in candidates:
        s = raw.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if _local_upload_file_relative(s) is not None:
            if _local_cv_file_exists(s):
                return _to_absolute_url(request, s)
            continue

    return None


@router.get("/me/candidatures")
def lister_mes_candidatures(
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> List[dict]:
    """
    Candidatures pour toutes les offres de l'entreprise connectée.
    Joint Candidature, Candidat et Offre.
    """
    rows = (
        db.query(Candidature, Candidat, Offre)
        .join(Candidat, Candidature.candidat_id == Candidat.id)
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(Offre.entreprise_id == entreprise.id)
        .order_by(Candidature.created_at.desc())
        .all()
    )

    out: List[dict] = []
    for cand, person, offre in rows:
        nom_complet = f"{person.prenom} {person.nom}".strip()
        out.append(
            {
                "id": str(cand.id),
                "offre_id": str(offre.id),
                "candidat_nom": nom_complet,
                "offre_titre": offre.title,
                "statut": cand.statut.value if cand.statut else "nouvelle",
                "score_ia": _normalize_score_ia(cand.score_cv_matching),
            }
        )
    return out


@router.get("/me/dashboard-stats")
def get_dashboard_stats(
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict:
    """
    Indicateurs agrégés pour le tableau de bord entreprise.
    """
    eid = entreprise.id

    total_candidats = (
        db.query(func.count(Candidature.id))
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(Offre.entreprise_id == eid)
        .scalar()
    )
    total_candidats = int(total_candidats or 0)

    offres_actives = (
        db.query(func.count(Offre.id))
        .filter(Offre.entreprise_id == eid, Offre.status == "active")
        .scalar()
    )
    offres_actives = int(offres_actives or 0)

    entretiens_prevus = (
        db.query(func.count(Candidature.id))
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(Offre.entreprise_id == eid)
        .filter(
            or_(
                Candidature.etape_actuelle.ilike("oral%"),
                Candidature.etape_actuelle.ilike("entretien%"),
            )
        )
        .scalar()
    )
    entretiens_prevus = int(entretiens_prevus or 0)

    accepted = (
        db.query(func.count(Candidature.id))
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(Offre.entreprise_id == eid)
        .filter(Candidature.statut == StatutCandidature.acceptee)
        .scalar()
    )
    accepted = int(accepted or 0)

    if total_candidats > 0:
        taux_conversion = round((accepted / total_candidats) * 100, 1)
    else:
        taux_conversion = 0.0

    active_offres = (
        db.query(Offre)
        .filter(Offre.entreprise_id == eid, Offre.status == "active")
        .order_by(Offre.created_at.desc())
        .all()
    )

    recrutements_en_cours: List[dict] = []
    for o in active_offres:
        count_c = (
            db.query(func.count(Candidature.id))
            .filter(Candidature.offre_id == o.id)
            .scalar()
        )
        count_c = int(count_c or 0)
        target = o.nombre_candidats_recherche
        if target is not None and int(target) > 0:
            progression = min(100, round((count_c / int(target)) * 100))
        else:
            progression = 0

        c_stage = (
            db.query(Candidature)
            .filter(
                Candidature.offre_id == o.id,
                Candidature.etape_actuelle.isnot(None),
                func.trim(Candidature.etape_actuelle) != "",
            )
            .order_by(Candidature.updated_at.desc())
            .first()
        )
        stage_label = (c_stage.etape_actuelle if c_stage else None) or "—"

        recrutements_en_cours.append(
            {
                "title": o.title or "Sans titre",
                "count_candidats": count_c,
                "progression": progression,
                "stage": stage_label,
            }
        )

    return {
        "nom_entreprise": entreprise.nom or "Entreprise",
        "total_candidats": total_candidats,
        "offres_actives": offres_actives,
        "entretiens_prevus": entretiens_prevus,
        "taux_conversion": taux_conversion,
        "recrutements_en_cours": recrutements_en_cours,
    }


@router.get("/me/candidatures/{candidature_id}/details")
def get_candidature_details(
    candidature_id: UUID,
    request: Request,
    entreprise=Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
) -> dict:
    """
    Détails d'une candidature (candidat, scores CV / écrit / oral, statut).
    """
    row = (
        db.query(Candidature, Offre)
        .join(Offre, Candidature.offre_id == Offre.id)
        .filter(
            Candidature.id == candidature_id,
            Offre.entreprise_id == entreprise.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidature introuvable.",
        )

    candidature, offre = row
    candidat = (
        db.query(Candidat).filter(Candidat.id == candidature.candidat_id).first()
    )
    if not candidat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidat introuvable.",
        )

    test_ecrit = (
        db.query(TestEcrit)
        .filter(TestEcrit.id_candidature == candidature.id)
        .order_by(desc(TestEcrit.id))
        .first()
    )
    score_ecrit = float(test_ecrit.score_ecrit) if test_ecrit else None

    score_oral: Optional[float] = None
    bind = db.get_bind()
    if bind is not None and sa_inspect(bind).has_table("tests_oraux"):
        test_oral = (
            db.query(TestOral)
            .filter(TestOral.id_candidature == candidature.id)
            .order_by(desc(TestOral.id))
            .first()
        )
        if test_oral is not None and test_oral.score_oral is not None:
            score_oral = float(test_oral.score_oral)

    cv_url = _resolve_cv_url(request, candidat, candidature)

    return {
        "candidate": {
            "nom": candidat.nom,
            "prenom": candidat.prenom,
            "email": candidat.email,
            "cin": candidat.cin,
            "cv_url": cv_url,
        },
        "scores": {
            "score_cv_matching": float(candidature.score_cv_matching)
            if candidature.score_cv_matching is not None
            else None,
            "score_ecrit": score_ecrit,
            "score_oral": score_oral,
        },
        "status": {
            "statut": candidature.statut.value if candidature.statut else "nouvelle",
            "etape_actuelle": _read_etape_actuelle(db, candidature.id),
        },
        "offre_titre": offre.title,
    }
