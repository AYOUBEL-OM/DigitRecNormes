"""
Banques de questions d'entretien oral par domaine et par niveau (FR), formulées pour le recrutement au Maroc.

Contexte implicite : entreprises et PME marocaines, marché local ou régional ; tout exemple chiffré doit
privilégier le dirham (DH / MAD), la TVA marocaine et l’IS lorsque la finance est évoquée.
Utilisé par `oral_questions_service` — pas d'appel LLM ici.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

DomainKey = Literal["it", "marketing", "finance", "general"]
LevelKey = Literal["junior", "confirme", "senior"]

# --- Questions fixes (obligatoires, jamais modifiées) ---
ORAL_FIXED_QUESTIONS: tuple[str, ...] = (
    "Présentez-vous.",
    "Parlez-moi de votre parcours et de vos expériences.",
    "Pourquoi avez-vous postulé à cette offre ?",
)

# Mots-clés pour détection du domaine (texte normalisé sans accents)
_DOMAIN_KEYWORDS: dict[DomainKey, tuple[str, ...]] = {
    "it": (
        "developpeur",
        "developpeuse",
        "devops",
        "software",
        "ingenieur logiciel",
        "ingenieur informatique",
        "informatique",
        "programmation",
        "full stack",
        "fullstack",
        "frontend",
        "backend",
        "cybersecurite",
        "cloud",
        "data engineer",
        "data scientist",
        "sysadmin",
        "reseau",
        "agile",
        "scrum",
        "python",
        "java",
        "javascript",
        "react",
        "angular",
        "node",
        "kubernetes",
        "docker",
        "sql",
        "git",
        "sre",
        "tech",
        "dsi",
    ),
    "marketing": (
        "marketing",
        "communication",
        "seo",
        "sea",
        "sem",
        "social media",
        "community",
        "marque",
        "brand",
        "campagne",
        "growth",
        "content",
        "redaction",
        "evenementiel",
        "crm",
        "acquisition",
        "notoriete",
    ),
    "finance": (
        "finance",
        "financier",
        "comptab",
        "audit",
        "controleur",
        "controle de gestion",
        "tresorerie",
        "bilan",
        "consolidation",
        "reporting",
        "fp&a",
        "fpa",
        "ifrs",
        "credit",
        "risque",
        "banque",
        "investissement",
        "m&a",
    ),
}


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def normalize_text_for_match(text: str) -> str:
    t = _strip_accents((text or "").lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _keyword_matches_blob(blob: str, kw: str) -> bool:
    """
    Correspondance mot ou expression : évite les faux positifs (ex. « it » dans « produit »).
    """
    k = (kw or "").strip()
    if not k:
        return False
    if " " in k:
        return k in blob
    return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", blob) is not None


def detect_domain(title: str, profile: str, description: str) -> DomainKey:
    """Infère le domaine à partir du titre, profil et description de l'offre."""
    blob = normalize_text_for_match(
        " ".join(x for x in (title, profile, description) if x)
    )
    if not blob:
        return "general"
    scores: dict[DomainKey, int] = {"it": 0, "marketing": 0, "finance": 0, "general": 0}
    for dom in ("it", "marketing", "finance"):
        for kw in _DOMAIN_KEYWORDS[dom]:
            if _keyword_matches_blob(blob, kw):
                scores[dom] += 1
    best = max(scores["it"], scores["marketing"], scores["finance"])
    if best == 0:
        return "general"
    winners = [d for d in ("it", "marketing", "finance") if scores[d] == best]
    if len(winners) == 1:
        return winners[0]  # type: ignore[return-value]
    # Départage : ordre IT > Marketing > Finance
    priority = ("it", "marketing", "finance")
    for p in priority:
        if p in winners:
            return p  # type: ignore[return-value]
    return "general"


def normalize_level(raw: str | None) -> LevelKey:
    if not raw:
        return "confirme"
    t = normalize_text_for_match(raw)
    if any(
        x in t
        for x in (
            "junior",
            "debutant",
            "stagiaire",
            "alternant",
            "jun",
        )
    ):
        return "junior"
    if any(
        x in t
        for x in (
            "senior",
            "lead",
            "expert",
            "manager",
            "directeur",
            "chef de projet",
            "principal",
        )
    ):
        return "senior"
    if any(x in t for x in ("confirme", "intermediaire", "experimente")):
        return "confirme"
    return "confirme"


# --- Banques par domaine et niveau ---

_BANKS: dict[DomainKey, dict[LevelKey, tuple[str, ...]]] = {
    "it": {
        "junior": (
            "Expliquez simplement un projet technique ou scolaire dont vous êtes fier.",
            "Quel langage ou outil avez-vous le plus utilisé jusqu’ici ?",
            "Comment apprenez-vous quand vous découvrez une technologie nouvelle ?",
            "Décrivez comment vous procédez pour corriger une erreur dans votre code.",
            "Qu’est-ce qui vous motive à progresser en développement ou en IT ?",
            "Comment organisez-vous vos tâches quand vous avez plusieurs sujets en parallèle ?",
            "Avez-vous déjà travaillé en équipe sur un livrable technique ? Comment avez-vous contribué ?",
            "Quelle documentation ou ressource consultez-vous en premier face à un blocage ?",
            "Comment testez-vous votre travail avant de le considérer comme terminé ?",
            "Parlez d’une difficulté technique que vous avez surmontée récemment.",
        ),
        "confirme": (
            "Expliquez un projet technique que vous avez réalisé.",
            "Quelle technologie maîtrisez-vous le plus ?",
            "Comment résolvez-vous un bug complexe ?",
            "Comment priorisez-vous les sujets techniques sur un projet avec des contraintes serrées ?",
            "Décrivez votre approche pour concevoir des tests automatisés pertinents.",
            "Comment présentez-vous un arbitrage technique à un produit ou à un manager ?",
            "Parlez d’un incident de production : diagnostic, priorisation et sortie de crise.",
            "Quels indicateurs de qualité logicielle suivez-vous sur vos missions ?",
            "Comment intégrez-vous la sécurité dans le cycle de développement ?",
            "Comment organisez-vous les revues de code pour garder une base cohérente ?",
            "Décrivez une optimisation de performance ou de coûts que vous avez menée.",
            "Comment validez-vous qu’une solution répond aux besoins métier ?",
            "Comment gérez-vous un désaccord technique prolongé au sein de l’équipe ?",
            "Parlez d’une migration technique ou d’une montée de version majeure.",
        ),
        "senior": (
            "Comment pilotez-vous une décision d’architecture sur un produit critique ?",
            "Décrivez comment vous encadrez la montée en compétences techniques de l’équipe.",
            "Quels critères utilisez-vous pour arbitrer dette technique, délais et valeur métier ?",
            "Comment structurez-vous la veille techno et les standards pour plusieurs équipes ?",
            "Parlez d’une situation où vous avez dû refondre ou stabiliser un système legacy.",
            "Comment mesurez-vous la fiabilité et la résilience de vos services en production ?",
            "Comment gérez-vous la relation avec la sécurité, l’infra et le métier sur un sujet sensible ?",
            "Décrivez votre approche du staffing et du mentoring sur des profils hétérogènes.",
            "Comment anticipez-vous la scalabilité et les coûts d’exploitation sur le long terme ?",
            "Parlez d’un échec ou d’un retard majeur : responsabilités, leçons et changements mis en place.",
        ),
    },
    "marketing": {
        "junior": (
            "Quel type de campagne ou d’action marketing avez-vous déjà contribué à mettre en œuvre ?",
            "Quels outils numériques maîtrisez-vous le mieux aujourd’hui ?",
            "Comment mesurez-vous si une action a bien fonctionné ?",
            "Qu’est-ce qui vous intéresse le plus dans le marketing de ce poste ?",
            "Comment préparez-vous un contenu ou un message pour une cible donnée ?",
            "Décrivez comment vous vous informez sur les tendances du secteur.",
            "Avez-vous déjà collaboré avec un graphiste, un commercial ou un produit ? Comment ?",
            "Comment organisez-vous votre veille concurrentielle ou sectorielle ?",
            "Quelle difficulté avez-vous rencontrée sur un projet marketing et comment l’avez-vous gérée ?",
            "Pourquoi la cohérence de marque vous semble-t-elle importante ?",
        ),
        "confirme": (
            "Quelle stratégie marketing avez-vous déjà mise en place ?",
            "Comment analysez-vous une campagne ?",
            "Quels outils utilisez-vous ?",
            "Comment construisez-vous un plan d’actions multicanal avec des objectifs mesurables ?",
            "Décrivez comment vous segmentez une audience et adaptez le message.",
            "Comment travaillez-vous avec les équipes commerciales ou produit sur un lancement ?",
            "Parlez d’un cas où le ROI était décevant : qu’avez-vous ajusté ?",
            "Comment priorisez-vous les canaux lorsque le budget est limité (contexte PME ou équipe marketing au Maroc) ?",
            "Quels KPI suivez-vous au quotidien et comment les présentez-vous ?",
            "Décrivez une expérience de test A/B ou d’itération rapide sur une campagne.",
            "Comment gérez-vous une crise de réputation ou un bad buzz sur les réseaux ?",
            "Parlez d’une collaboration avec une agence ou un prestataire : objectifs et suivi.",
        ),
        "senior": (
            "Comment définissez-vous la stratégie marketing sur un horizon 12 à 24 mois ?",
            "Décrivez comment vous alignez marketing, vente et produit sur la croissance.",
            "Comment pilotez-vous le budget marketing et l’allocation par canal ?",
            "Parlez d’un repositionnement de marque ou d’un changement de cible majeur.",
            "Comment intégrez-vous la donnée client et l’attribution dans vos décisions ?",
            "Comment structurez-vous une équipe marketing et ses objectifs individuels ?",
            "Décrivez une négociation difficile avec la direction ou les finance sur un investissement.",
            "Comment anticipez-vous les évolutions réglementaires ou sociétales impactant le marketing au Maroc et dans la région ?",
            "Parlez d’une innovation marketing qui a durablement changé les résultats.",
            "Comment mesurez-vous et communiquez la valeur du marketing auprès du comité de direction ?",
        ),
    },
    "finance": {
        "junior": (
            "Quels logiciels ou tableurs utilisez-vous le plus pour vos analyses ?",
            "Comment vérifiez-vous qu’un calcul ou un report est exact avant envoi ?",
            "Décrivez une tâche récurrente en finance ou contrôle de gestion que vous maîtrisez.",
            "Comment organisez-vous vos dossiers et échéances comptables ou de clôture ?",
            "Qu’est-ce qui vous attire dans la finance appliquée à ce secteur ?",
            "Avez-vous déjà participé à un budget ou un forecast ? Dans quel rôle ?",
            "Comment apprenez-vous les normes ou règles spécifiques à une société marocaine ou à votre groupe local ?",
            "Parlez d’une erreur détectée à temps : comment l’avez-vous traitée ?",
            "Comment lisez-vous un tableau de flux ou un compte de résultat à un niveau basique ?",
            "Quelles sources utilisez-vous pour suivre l’actualité financière ?",
        ),
        "confirme": (
            "Comment analysez-vous un bilan financier ?",
            "Expliquez une décision financière importante que vous avez prise.",
            "Quels outils financiers utilisez-vous ?",
            "Comment construisez-vous un tableau de bord de pilotage pour la direction ?",
            "Décrivez votre méthode pour analyser les écarts budget / réalisé.",
            "Comment travaillez-vous avec l’audit interne ou externe ?",
            "Parlez d’une optimisation de trésorerie ou de coûts que vous avez proposée.",
            "Comment évaluez-vous la rentabilité d’un projet ou d’un investissement au regard du cadre fiscal marocain (IS, TVA) ?",
            "Décrivez une clôture ou un reporting sous contrainte de délai.",
            "Comment intégrez-vous les risques financiers dans vos analyses ?",
            "Parlez d’une collaboration avec le commercial ou les opérations sur une offre tarifaire (TTC / HT, TVA marocaine).",
        ),
        "senior": (
            "Comment arbitrez-vous investissements, dividendes et besoin en fonds de roulement ?",
            "Décrivez comment vous préparez la relation avec les banques marocaines ou les investisseurs sur le marché national ou régional.",
            "Comment pilotez-vous la transformation du contrôle de gestion ou de la fonction finance ?",
            "Parlez d’une restructuration financière ou d’un plan de retour à la rentabilité.",
            "Comment intégrez-vous ESG et risques non financiers dans la stratégie groupe ?",
            "Comment présentez-vous des scénarios macroéconomiques au comité exécutif ?",
            "Décrivez votre approche du cash culture et de la discipline budgétaire transverse.",
            "Comment gérez-vous une crise de liquidité ou un covenant sous pression ?",
            "Parlez d’un M&A, d’une cession ou d’une due diligence dont vous avez été proche.",
            "Comment mesurez-vous la performance de la fonction finance et de ses équipes ?",
        ),
    },
    "general": {
        "junior": (
            "Quelles missions ou projets récents illustrent le mieux votre motivation pour ce poste ?",
            "Comment organisez-vous votre travail au quotidien ?",
            "Quelles compétences souhaitez-vous développer en priorité ici ?",
            "Décrivez une situation où vous avez demandé de l’aide et ce que vous en avez appris.",
            "Comment gérez-vous les retours ou les critiques sur votre travail ?",
            "Quel environnement de travail vous permet d’être le plus efficace ?",
            "Parlez d’une expérience de travail en équipe qui vous a marqué.",
            "Comment vous formez-vous en continu dans votre domaine ?",
            "Quelle qualité personnelle vous aide le plus dans votre métier ?",
            "Pourquoi ce secteur ou cette fonction vous intéresse-t-il ?",
        ),
        "confirme": (
            "Décrivez un projet professionnel récent dont vous êtes fier et votre rôle précis.",
            "Comment priorisez-vous vos missions lorsque tout semble urgent ?",
            "Parlez d’un conflit ou d’un désaccord : comment l’avez-vous résolu ?",
            "Comment assurez-vous la qualité de vos livrables avant de les transmettre ?",
            "Quels indicateurs suivez-vous pour savoir si votre travail apporte de la valeur ?",
            "Comment collaborez-vous avec d’autres services ou métiers au sein d’une structure implantée au Maroc ?",
            "Décrivez une situation où vous avez dû vous adapter rapidement à un changement.",
            "Comment présentez-vous vos résultats à un manager ou un client ?",
            "Parlez d’une erreur professionnelle : qu’avez-vous corrigé ensuite ?",
            "Quels outils ou méthodes utilisez-vous pour rester efficace ?",
            "Comment gérez-vous la charge lors des périodes de forte activité ?",
            "Pourquoi pensez-vous correspondre aux attentes de ce poste aujourd’hui ?",
        ),
        "senior": (
            "Comment définissez-vous la vision et les priorités de votre domaine sur l’année à venir ?",
            "Décrivez comment vous influencez les décisions stratégiques de l’entreprise.",
            "Parlez d’une transformation ou d’un changement majeur que vous avez conduit.",
            "Comment développez-vous les talents et déléguez-vous sans perdre en qualité ?",
            "Quels arbitrages difficiles avez-vous dû faire entre court et long terme ?",
            "Comment gérez-vous les parties prenantes internes et externes sensibles ?",
            "Décrivez votre approche du pilotage par la donnée et de la transparence.",
            "Parlez d’une situation où vous avez dû dire non à la direction : comment l’avez-vous argumenté ?",
            "Comment mesurez-vous l’impact de votre fonction sur la performance globale ?",
            "Quelle est votre méthode pour anticiper les risques majeurs dans votre périmètre ?",
        ),
    },
}


def get_bank(domain: DomainKey, level: LevelKey) -> tuple[str, ...]:
    """Banque principale domaine × niveau (le domaine « general » couvre le profil non classé)."""
    return _BANKS.get(domain, _BANKS["general"]).get(level, _BANKS["general"]["confirme"])


def merge_dynamic_pool(domain: DomainKey, level: LevelKey) -> list[str]:
    """
    Pool élargi : spécifique domaine+niveau + renfort « general » même niveau
    pour éviter les manques et diversifier les tirages.
    """
    primary = list(get_bank(domain, level))
    extra = list(get_bank("general", level)) if domain != "general" else []
    return primary + extra
