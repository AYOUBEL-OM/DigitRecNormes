"""
Service d'envoi d'emails SMTP.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from uuid import UUID

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def send_email(to_email: str, subject: str, body: str) -> None:
    """
    Envoie un email via SMTP.
    Fonction synchrone, à appeler depuis une tâche en arrière-plan.
    """
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning("SMTP non configuré, email non envoyé à %s", to_email)
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


def send_acceptance_email(
    candidat_email: str,
    candidat_name: str,
    job_title: str,
    offre_id: UUID,
) -> None:
    base = (settings.FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
    quiz_url = f"{base}/quiz/{offre_id}"
    subject = f"Invitation au Test Écrit - {job_title}"
    body = (
        f"Bonjour {candidat_name},\n\n"
        f"Votre profil a été retenu pour le poste de {job_title}. "
        f"Nous vous invitons à passer un test écrit en cliquant sur ce lien: {quiz_url}\n\n"
        "Cordialement,\n"
        "L'équipe de recrutement.\n"
    )
    send_email(to_email=candidat_email, subject=subject, body=body)


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
