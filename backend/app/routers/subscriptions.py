"""
Abonnements Stripe (plans, Checkout, webhook, état courant).
"""
from __future__ import annotations

import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants.subscription_plans import canonical_plan_code, get_plan, list_plans_public, public_plan_code
from app.core.auth import get_entreprise_from_token
from app.database import get_db
from app.models.entreprise import Entreprise
from app.schemas.subscription import (
    ConfirmCheckoutBody,
    ConfirmCheckoutResponse,
    CreateCheckoutBody,
    CreateCheckoutResponse,
    SubscriptionMeOut,
)
from app.services.stripe_service import (
    confirm_checkout_session_for_entreprise,
    create_checkout_session,
    handle_checkout_session_completed,
    handle_invoice_payment_succeeded,
    sync_subscription_from_stripe_obj,
)
from app.services.subscription_access import (
    FREE_TRIAL_OFFERS_EXHAUSTED_MESSAGE,
    count_active_offers,
    count_all_offers,
    ensure_default_trial_subscription,
    get_active_subscription_for_entreprise,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["Abonnements"])


@router.get("/plans")
def list_plans():
    return list_plans_public()


@router.post("/create-checkout-session", response_model=CreateCheckoutResponse)
def create_checkout(
    body: CreateCheckoutBody,
    entreprise: Entreprise = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    code = canonical_plan_code(body.plan_code)
    if code == "TRIAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le plan d’essai ne peut pas être souscrit via Stripe. Choisissez un pack payant.",
        )
    try:
        get_plan(code)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan inconnu.",
        ) from None
    try:
        url, sid = create_checkout_session(db, settings, entreprise, code)
        return CreateCheckoutResponse(checkout_url=url, session_id=sid)
    except RuntimeError as e:
        logger.warning("Stripe checkout refusé ou config incomplète: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except ValueError as e:
        logger.warning("create-checkout-session paramètre invalide: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("create_checkout_session inattendu")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Impossible de créer la session de paiement Stripe. "
                "Vérifiez les logs serveur et la configuration (clé secrète, Price IDs, mode test/live)."
            ),
        ) from e


@router.post("/confirm-checkout-session", response_model=ConfirmCheckoutResponse)
def confirm_checkout_session(
    body: ConfirmCheckoutBody,
    entreprise: Entreprise = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    """
    Fallback fiable : synchronise l’abonnement depuis Stripe (webhook injoignable en local
    ou événement en retard) après le retour Checkout avec session_id.
    """
    settings = get_settings()
    try:
        data = confirm_checkout_session_for_entreprise(
            db, settings, entreprise, body.session_id
        )
        return ConfirmCheckoutResponse(
            ok=bool(data.get("ok", True)),
            plan_code=str(data.get("plan_code", "")),
            status=str(data.get("status", "")),
            subscription_id=str(data.get("subscription_id", "")),
        )
    except ValueError as e:
        logger.warning("confirm-checkout-session refus: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        logger.error("confirm-checkout-session erreur métier: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("confirm-checkout-session inattendu")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Impossible de confirmer la session auprès de Stripe. Réessayez ou contactez le support.",
        ) from e


@router.get("/me", response_model=SubscriptionMeOut)
def subscription_me(
    entreprise: Entreprise = Depends(get_entreprise_from_token),
    db: Session = Depends(get_db),
):
    ensure_default_trial_subscription(db, entreprise.id)
    sub = get_active_subscription_for_entreprise(db, entreprise.id)
    if not sub:
        return SubscriptionMeOut(
            has_active_subscription=False,
            can_create_offer=False,
            offers_used=0,
            offers_limit=None,
            message="Aucune formule active — reconnectez-vous ou contactez le support.",
        )
    try:
        pl = get_plan(sub.plan_code)
        label = pl.label
        max_o = pl.max_active_offers
        payment_required = pl.payment_required
        is_trial = pl.is_trial
    except KeyError:
        label = sub.plan_code
        max_o = None
        payment_required = False
        is_trial = False
    n_active = count_active_offers(db, entreprise.id)
    n_all = count_all_offers(db, entreprise.id)
    remaining = None if max_o is None else max(0, int(max_o) - int(n_active))

    if is_trial and max_o is not None:
        offers_used = int(n_all)
        offers_limit = int(max_o)
        can_create = n_all < max_o
        trial_exhausted = not can_create
        msg = FREE_TRIAL_OFFERS_EXHAUSTED_MESSAGE if not can_create else None
    elif max_o is not None:
        offers_used = int(n_active)
        offers_limit = int(max_o)
        can_create = n_active < max_o
        trial_exhausted = False
        msg = (
            (
                f"Nombre maximal d’offres actives atteint ({max_o}). "
                "Passez au pack illimité ou désactivez une offre existante."
            )
            if not can_create
            else None
        )
    else:
        offers_used = int(n_active)
        offers_limit = None
        can_create = True
        trial_exhausted = False
        msg = None

    out = SubscriptionMeOut(
        has_active_subscription=True,
        plan_code=public_plan_code(sub.plan_code),
        plan_label=label,
        status=sub.status,
        billing_cycle=sub.billing_cycle,
        end_date=sub.end_date,
        start_date=sub.start_date,
        currency=sub.currency,
        amount_cents=sub.amount_cents,
        max_active_offers=max_o,
        active_offers_count=n_active,
        offers_remaining=remaining,
        payment_required=payment_required,
        is_trial=is_trial,
        trial_exhausted=trial_exhausted,
        offers_used=offers_used,
        offers_limit=offers_limit,
        can_create_offer=can_create,
        message=msg,
    )
    logger.info(
        "GET /subscriptions/me: entreprise_id=%s internal_plan=%s public_plan=%s can_create_offer=%s",
        entreprise.id,
        sub.plan_code,
        out.plan_code,
        can_create,
    )
    return out


_HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "invoice.payment_succeeded",
        "customer.subscription.created",
    },
)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook Stripe : corps brut obligatoire pour la vérification de signature.
    Réponses : 200 pour tout événement vérifié (traité, ignoré ou erreur métier loguée) ;
    400 uniquement si la signature ne peut pas être validée.
    """
    settings = get_settings()
    wh_secret = (settings.STRIPE_WEBHOOK_SECRET or "").strip()
    if not wh_secret:
        logger.error("WEBHOOK: STRIPE_WEBHOOK_SECRET non configuré")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="STRIPE_WEBHOOK_SECRET non configuré.",
        )

    # Corps brut uniquement — ne jamais parser en JSON avant construct_event.
    payload: bytes = await request.body()
    if not isinstance(payload, bytes):
        payload = bytes(payload) if payload else b""

    sig_header = request.headers.get("stripe-signature") or ""
    logger.info(
        "WEBHOOK RECEIVED bytes=%s stripe_signature_present=%s",
        len(payload),
        bool(sig_header.strip()),
    )

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            wh_secret,
        )
    except ValueError as e:
        # Hors signature : ne pas renvoyer 400 (ex. corps vide, JSON corrompu, double lecture du body).
        logger.warning(
            "WEBHOOK: construct_event ValueError (corps non JSON / vide — vérifier raw body & middleware): %s",
            e,
        )
        return {"status": "ignored", "reason": "invalid_payload", "received": True}
    except stripe.SignatureVerificationError as e:
        logger.warning("WEBHOOK: échec vérification signature Stripe: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature Stripe invalide.",
        ) from e

    etype = event.get("type") or ""
    event_id = event.get("id")
    logger.info("WEBHOOK EVENT TYPE: %s event.id=%s", etype, event_id)

    if etype not in _HANDLED_EVENT_TYPES:
        logger.info("WEBHOOK: type non géré — 200 ignored type=%s", etype)
        return {"status": "ignored", "event": etype}

    data_object = (event.get("data") or {}).get("object") or {}

    try:
        if etype == "checkout.session.completed":
            logger.info("WEBHOOK: CHECKOUT SESSION COMPLETED — calling handle_checkout_session_completed")
            handle_checkout_session_completed(db, settings, data_object)
        elif etype == "invoice.payment_succeeded":
            handle_invoice_payment_succeeded(db, settings, data_object)
        elif etype == "customer.subscription.created":
            sync_subscription_from_stripe_obj(db, settings, data_object)
    except Exception:
        logger.exception("WEBHOOK: erreur handler type=%s event.id=%s", etype, event_id)
        # 200 : Stripe ne doit pas boucler indéfiniment ; erreur corrigée côté données / relance manuelle.
        return {
            "status": "error",
            "event": etype,
            "received": True,
            "message": "Handler exception logged server-side.",
        }

    return {"status": "ok", "event": etype, "received": True}
