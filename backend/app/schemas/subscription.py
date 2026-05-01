from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class PlanPublicOut(BaseModel):
    code: str
    label: str
    price: float
    currency: str
    billing_note: Optional[str] = None
    payment_required: bool = False
    is_trial: bool = False
    features: List[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)


class CreateCheckoutBody(BaseModel):
    plan_code: str = Field(..., min_length=2, max_length=32)


class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class ConfirmCheckoutBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=256)


class ConfirmCheckoutResponse(BaseModel):
    ok: bool = True
    plan_code: str
    status: str
    subscription_id: str


class SubscriptionMeOut(BaseModel):
    has_active_subscription: bool
    # Code métier exposé : ESSAI_GRATUIT | PACK_LIMITE | PACK_ILLIMITE
    plan_code: Optional[str] = None
    plan_label: Optional[str] = None
    status: Optional[str] = None
    billing_cycle: Optional[str] = None
    end_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    currency: Optional[str] = None
    amount_cents: Optional[int] = None
    max_active_offers: Optional[int] = None
    active_offers_count: int = 0
    offers_remaining: Optional[int] = None
    payment_required: bool = False
    is_trial: bool = False
    trial_exhausted: bool = False
    # Quotas (source de vérité pour le front)
    offers_used: int = 0
    offers_limit: Optional[int] = None
    can_create_offer: bool = True
    message: Optional[str] = None
