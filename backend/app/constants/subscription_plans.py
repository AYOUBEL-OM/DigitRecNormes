"""
Définition des offres SaaS : essai gratuit + 2 packs payants (Stripe).
Les anciens codes BASIC / PRO / PREMIUM sont mappés pour compatibilité (voir ``_canonical_plan_code``).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional


# Anciens plans → nouveaux (données existantes + webhooks avec anciens price id éventuels côté mapping prix)
LEGACY_PLAN_CODE_TO_CANONICAL: Dict[str, str] = {
    "BASIC": "LIMITED",
    "PRO": "UNLIMITED",
    "PREMIUM": "UNLIMITED",
    # Alias API / front (codes exposés)
    "ESSAI_GRATUIT": "TRIAL",
    "PACK_LIMITE": "LIMITED",
    "PACK_ILLIMITE": "UNLIMITED",
}


def canonical_plan_code(code: Optional[str]) -> str:
    """Code métier normalisé (TRIAL / LIMITED / UNLIMITED)."""
    c = (code or "").strip().upper()
    return LEGACY_PLAN_CODE_TO_CANONICAL.get(c, c)


# Codes exposés `/api/subscriptions/me` et catalogue `/plans`
PUBLIC_PLAN_BY_INTERNAL: Dict[str, str] = {
    "TRIAL": "ESSAI_GRATUIT",
    "LIMITED": "PACK_LIMITE",
    "UNLIMITED": "PACK_ILLIMITE",
}


def public_plan_code(internal_code: Optional[str]) -> str:
    c = canonical_plan_code(internal_code or "")
    return PUBLIC_PLAN_BY_INTERNAL.get(c, c)


@dataclass(frozen=True)
class SaaSPlan:
    """Plan affiché côté API et utilisé pour les quotas d’offres."""

    code: str
    label: str
    monthly_price_mad: Decimal
    currency: str
    max_active_offers: Optional[int]
    payment_required: bool
    is_trial: bool
    written_tests: bool
    oral_tests: bool
    ai_features: bool
    proctoring: bool
    detailed_reports: bool
    feature_bullets: tuple[str, ...]

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "code": public_plan_code(self.code),
            "label": self.label,
            "price": float(self.monthly_price_mad),
            "currency": self.currency,
            "payment_required": self.payment_required,
            "is_trial": self.is_trial,
            "billing_note": (
                "Sans engagement de paiement"
                if self.is_trial
                else "Abonnement mensuel (Stripe, mode test)"
            ),
            "features": list(self.feature_bullets),
            "limits": {
                "max_active_offers": self.max_active_offers,
                "written_tests": self.written_tests,
                "oral_tests": self.oral_tests,
                "ai_features": self.ai_features,
                "proctoring": self.proctoring,
                "detailed_reports": self.detailed_reports,
            },
        }


PLAN_TRIAL = SaaSPlan(
    code="TRIAL",
    label="Essai gratuit",
    monthly_price_mad=Decimal("0"),
    currency="mad",
    max_active_offers=1,
    payment_required=False,
    is_trial=True,
    written_tests=True,
    oral_tests=True,
    ai_features=True,
    proctoring=True,
    detailed_reports=True,
    feature_bullets=(
        "1 offre gratuite à la création",
        "Découverte complète de la plateforme",
        "Aucune carte bancaire à l’inscription",
    ),
)

PLAN_LIMITED = SaaSPlan(
    code="LIMITED",
    label="Pack limité",
    monthly_price_mad=Decimal("299"),
    currency="mad",
    max_active_offers=3,
    payment_required=True,
    is_trial=False,
    written_tests=True,
    oral_tests=True,
    ai_features=True,
    proctoring=True,
    detailed_reports=True,
    feature_bullets=(
        "Jusqu’à 3 offres actives simultanées",
        "Accès complet après souscription",
    ),
)

PLAN_UNLIMITED = SaaSPlan(
    code="UNLIMITED",
    label="Pack illimité",
    monthly_price_mad=Decimal("799"),
    currency="mad",
    max_active_offers=None,
    payment_required=True,
    is_trial=False,
    written_tests=True,
    oral_tests=True,
    ai_features=True,
    proctoring=True,
    detailed_reports=True,
    feature_bullets=(
        "Offres actives illimitées (pas de plafond)",
        "Accès complet après souscription",
    ),
)

PLANS_BY_CODE: Dict[str, SaaSPlan] = {
    PLAN_TRIAL.code: PLAN_TRIAL,
    PLAN_LIMITED.code: PLAN_LIMITED,
    PLAN_UNLIMITED.code: PLAN_UNLIMITED,
}


def get_plan(code: str) -> SaaSPlan:
    key = canonical_plan_code(code)
    if key not in PLANS_BY_CODE:
        raise KeyError(f"Plan inconnu: {code}")
    return PLANS_BY_CODE[key]


def list_plans_public() -> List[Dict[str, Any]]:
    """Catalogue affichage (essai + 2 packs payants)."""
    return [p.to_public_dict() for p in (PLAN_TRIAL, PLAN_LIMITED, PLAN_UNLIMITED)]


def plan_rank(plan_code: str) -> int:
    """Ordre marketing / upgrade (conservé pour d’éventuels garde-fous futurs)."""
    c = canonical_plan_code(plan_code)
    return {"TRIAL": 1, "LIMITED": 2, "UNLIMITED": 3}.get(c, 0)
