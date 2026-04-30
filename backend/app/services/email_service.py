"""
Service d'envoi d'emails SMTP et préparation accès entretien oral (token + email).
"""
from __future__ import annotations

import logging
import re
import secrets
import smtplib
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.candidat import Candidat
from app.models.candidature import Candidature
from app.models.offre import Offre
from app.models.test_oral import TestOral

logger = logging.getLogger(__name__)
settings = get_settings()

_TZ_CASABLANCA = ZoneInfo("Africa/Casablanca")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_datetime_fr_email(dt: datetime) -> str:
    """Affichage type « 21/04/2026 à 14:30 » (UTC → Africa/Casablanca)."""
    return _normalize_to_utc(dt).astimezone(_TZ_CASABLANCA).strftime("%d/%m/%Y à %H:%M")


def _written_test_interval_sentence(sent_at: datetime, offre_date_fin: datetime | None) -> str:
    start_s = format_datetime_fr_email(sent_at)
    if offre_date_fin is not None:
        end_s = format_datetime_fr_email(offre_date_fin)
        return (
            f"Vous pouvez passer le test écrit entre le {start_s} et le {end_s}.\n\n"
        )
    return (
        f"Vous pouvez commencer le test écrit à partir du {start_s}. "
        "La date de clôture de l'offre n'est pas renseignée dans notre système ; "
        "contactez l'équipe de recrutement pour les délais.\n\n"
    )


def _oral_interview_interval_sentence(sent_at: datetime, offre_date_fin: datetime | None) -> str:
    start_s = format_datetime_fr_email(sent_at)
    if offre_date_fin is not None:
        end_s = format_datetime_fr_email(offre_date_fin)
        return (
            f"Vous pouvez passer votre entretien oral entre le {start_s} et le {end_s}.\n\n"
        )
    return (
        f"Vous pouvez commencer votre entretien oral à partir du {start_s}. "
        "La date de clôture de l'offre n'est pas renseignée dans notre système ; "
        "contactez l'équipe de recrutement pour les délais.\n\n"
    )


def _offre_still_open_for_email(offre_date_fin: datetime | None, sent_at: datetime) -> bool:
    """False si la clôture d'offre est strictement avant l'envoi (bonus : ne pas inviter sur offre expirée)."""
    if offre_date_fin is None:
        return True
    end = _normalize_to_utc(offre_date_fin)
    return end >= sent_at


def _email_looks_valid(email: str | None) -> bool:
    if not email or not str(email).strip():
        return False
    e = str(email).strip()
    return bool(_EMAIL_RE.match(e))


def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Envoie un email via SMTP.
    Fonction synchrone, à appeler depuis une tâche en arrière-plan.
    """
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning(
            "SMTP non configuré (host/user/pass), email non envoyé à %s — "
            "vérifiez SMTP_HOST, SMTP_USER, SMTP_PASS dans .env",
            to_email,
        )
        return

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.sendmail(msg["From"], [to_email], msg.as_string())
    logger.info("Email envoyé à %s (sujet: %s)", to_email, subject[:80])


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    subject = "Réinitialisation de votre mot de passe DigitRec"
    body = (
        "Bonjour,\n\n"
        "Nous avons reçu une demande de réinitialisation de mot de passe pour votre compte DigitRec.\n"
        "Cliquez sur le lien suivant pour définir un nouveau mot de passe :\n"
        f"{reset_url}\n\n"
        "Ce lien est valable pendant 30 minutes.\n"
        "Si vous n’êtes pas à l’origine de cette demande, vous pouvez ignorer cet email.\n\n"
        "Cordialement,\n"
        "L'équipe DigitRec.\n"
    )
    send_email(to_email=to_email, subject=subject, body=body)


def send_acceptance_email(
    candidat_email: str,
    candidat_name: str,
    job_title: str,
    offre_id: UUID,
    offre_date_fin: datetime | None = None,
) -> None:
    sent_at = datetime.now(timezone.utc)
    if not _offre_still_open_for_email(offre_date_fin, sent_at):
        logger.warning(
            "send_acceptance_email: envoi annulé — date_fin_offres antérieure à l'envoi (offre %s)",
            offre_id,
        )
        return

    base = (settings.FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
    quiz_url = f"{base}/quiz/{offre_id}"
    subject = f"Invitation au Test Écrit - {job_title}"
    interval_para = _written_test_interval_sentence(sent_at, offre_date_fin)
    body = (
        f"Bonjour {candidat_name},\n\n"
        f"Votre profil a été retenu pour le poste de {job_title}. "
        f"Nous vous invitons à passer un test écrit en cliquant sur ce lien: {quiz_url}\n\n"
        f"{interval_para}"
        "Cordialement,\n"
        "L'équipe de recrutement.\n"
    )
    send_email(to_email=candidat_email, subject=subject, body=body)


def send_oral_invitation_email(
    candidat_email: str,
    candidat_name: str,
    job_title: str,
    access_token: str,
    offre_date_fin: datetime | None = None,
) -> None:
    """Invitation à l'entretien oral après réussite au test écrit (status_reussite ; lien par token texte)."""
    if not _email_looks_valid(candidat_email):
        logger.warning(
            "send_oral_invitation_email: adresse invalide, envoi annulé (%r)",
            candidat_email,
        )
        return

    sent_at = datetime.now(timezone.utc)
    if not _offre_still_open_for_email(offre_date_fin, sent_at):
        logger.warning(
            "send_oral_invitation_email: envoi annulé — date_fin_offres antérieure à l'envoi",
        )
        return

    base = (settings.FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
    # Jeton en query (une redirection front le stocke en localStorage puis nettoie l’URL)
    safe_token = quote(access_token.strip(), safe="")
    oral_url = f"{base}/interview?oral_token={safe_token}"
    subject = f"Convocation — entretien oral supervisé — {job_title}"
    interval_para = _oral_interview_interval_sentence(sent_at, offre_date_fin)
    body = (
        f"Bonjour {candidat_name},\n\n"
        f"Suite à la réussite de votre test écrit, nous vous invitons à passer l’entretien oral pour le poste "
        f"« {job_title} ». Ce message constitue votre convocation à cet entretien, qui se déroule en ligne "
        f"dans un cadre supervisé.\n\n"
        f"{interval_para}"
        "— Accès à votre entretien oral —\n"
        "Veuillez utiliser le lien personnel ci-dessous (ne le partagez pas ; il est nominatif) :\n"
        f"{oral_url}\n\n"
        "— Conditions de passage —\n"
        "Pour garantir la qualité de l’échange, nous vous remercions de vous placer dans un endroit calme, "
        "de disposer d’une connexion internet stable, et d’utiliser un équipement doté d’une caméra et d’un "
        "microphone en bon état de fonctionnement. Une luminosité suffisante sur votre visage, une tenue "
        "correcte et professionnelle, ainsi que des réponses claires, structurées et posées contribueront "
        "positivement à votre passage.\n\n"
        "— Déroulement supervisé —\n"
        "L’entretien s’inscrit dans un dispositif de supervision technique (proctoring) visant à assurer le "
        "bon déroulement de la session pour tous les candidats. Conformément à ce dispositif, votre présence "
        "face à la caméra est attendue pendant toute la durée de l’entretien. Des sorties du mode plein écran "
        "ou des changements d’onglet du navigateur peuvent être enregistrés. L’usage du téléphone, de documents "
        "non autorisés ou de toute aide extérieure n’est pas permis pendant la session. Certains comportements "
        "peuvent être signalés à titre d’anomalies (par exemple : regards fréquemment détournés de l’écran, "
        "absence prolongée du champ de la caméra, ou présence d’une autre personne). Tout manquement grave aux "
        "consignes peut entraîner l’invalidation de l’entretien. Nous vous remercions de bien vouloir respecter "
        "l’ensemble de ces modalités.\n\n"
        "Pour toute difficulté technique avant le début de la session, contactez l’équipe de recrutement par "
        "les canaux habituels.\n\n"
        "Cordialement,\n"
        "L'équipe de recrutement.\n"
    )
    send_email(to_email=candidat_email.strip(), subject=subject, body=body)


def send_rejection_email(
    candidat_email: str, candidat_name: str, job_title: str, ai_analysis_report: str
) -> None:
    subject = f"Mise à jour concernant votre candidature - {job_title}"
    body = (
        f"Bonjour {candidat_name},\n\n"
        f"Nous vous remercions de l'intérêt que vous portez à notre entreprise pour le poste de {job_title}.\n"
        "Après une analyse approfondie de votre CV, nous avons le regret de vous informer que votre profil "
        "ne correspond pas totalement à nos critères actuels pour ce poste.\n\n"
        "Voici un retour basé sur l'analyse de vos compétences par rapport à nos prérequis :\n"
        f"{ai_analysis_report}\n\n"
        "Nous vous souhaitons une excellente continuation dans vos recherches.\n\n"
        "Cordialement,\n"
        "L'équipe de recrutement.\n"
    )
    send_email(to_email=candidat_email, subject=subject, body=body)


def _new_oral_access_token() -> str:
    """Jeton opaque texte (compatible colonne TEXT, pas UUID)."""
    return secrets.token_urlsafe(48)


def ensure_oral_access_and_maybe_email(db: Session, candidature_id: UUID) -> bool:
    """
    À appeler lorsque le test écrit est marqué réussi (``tests_ecrits.status_reussite`` True) :
    - assure une ligne `tests_oraux` pour la candidature (token + status),
    - envoie l'email d'invitation uniquement à la première attribution du token.

    Retourne True si le flux s'est terminé sans erreur DB bloquante.
    En cas d'échec DB, effectue rollback et retourne False (session réutilisable).
    """
    candidature = (
        db.query(Candidature).filter(Candidature.id == candidature_id).first()
    )
    if not candidature:
        logger.warning(
            "ensure_oral_access: candidature %s introuvable après test écrit",
            candidature_id,
        )
        return False

    offre = db.query(Offre).filter(Offre.id == candidature.offre_id).first()
    candidat = db.query(Candidat).filter(Candidat.id == candidature.candidat_id).first()
    if not offre:
        logger.warning(
            "ensure_oral_access: offre %s introuvable pour candidature %s",
            candidature.offre_id,
            candidature_id,
        )
        return False
    if not candidat:
        logger.warning(
            "ensure_oral_access: candidat introuvable pour candidature %s",
            candidature_id,
        )
        return False

    oral = (
        db.query(TestOral).filter(TestOral.id_candidature == candidature_id).first()
    )
    token_before = (oral.candidate_access_token or "").strip() if oral else ""

    now = datetime.now(timezone.utc)

    try:
        if not oral:
            oral = TestOral(
                id=uuid.uuid4(),
                id_candidature=candidature_id,
                candidate_access_token=_new_oral_access_token(),
                status="pending",
                date_passage=now,
                phone_detected=False,
                other_person_detected=False,
                presence_anomaly_detected=False,
                suspicious_movements_count=0,
            )
            db.add(oral)
        elif not (oral.candidate_access_token or "").strip():
            oral.candidate_access_token = _new_oral_access_token()
            if oral.status is None or not str(oral.status).strip():
                oral.status = "pending"
            if oral.date_passage is None:
                oral.date_passage = now
            db.add(oral)

        db.commit()
        reloaded = db.get(TestOral, oral.id)
        if reloaded is not None:
            oral = reloaded
    except IntegrityError as exc:
        db.rollback()
        logger.warning(
            "ensure_oral_access: IntegrityError sur tests_oraux pour candidature %s — "
            "rollback effectué ; préparation accès oral / envoi email NON effectués dans cette requête "
            "(conflit de contrainte ou insertion concurrente). Détail: %s",
            candidature_id,
            exc,
        )
        return False
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "ensure_oral_access: échec commit tests_oraux pour candidature %s: %s",
            candidature_id,
            exc,
        )
        return False

    token_after = (oral.candidate_access_token or "").strip()
    if not token_after:
        logger.error(
            "ensure_oral_access: token vide après commit pour candidature %s",
            candidature_id,
        )
        return False

    # Premier jeton attribué dans cette transaction → email unique (évite doublon si token déjà là)
    should_email = not token_before
    if not should_email:
        logger.debug(
            "ensure_oral_access: token déjà présent pour candidature %s, pas de nouvel email",
            candidature_id,
        )
        return True

    if not _email_looks_valid(candidat.email):
        logger.warning(
            "ensure_oral_access: email candidat absent ou invalide pour candidature %s, "
            "invitation oral non envoyée (token créé en base).",
            candidature_id,
        )
        return True

    try:
        send_oral_invitation_email(
            candidat_email=candidat.email.strip(),
            candidat_name=f"{candidat.prenom} {candidat.nom}".strip() or "Candidat",
            job_title=offre.title or "votre candidature",
            access_token=token_after,
            offre_date_fin=offre.date_fin_offres,
        )
    except Exception:
        logger.exception(
            "ensure_oral_access: échec envoi SMTP invitation oral (candidature %s) — "
            "la ligne tests_oraux est toutefois enregistrée.",
            candidature_id,
        )

    return True
