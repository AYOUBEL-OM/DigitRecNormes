"""
Intégration Stripe (Checkout, clients, synchro abonnement).
Paiement : packs LIMITED et UNLIMITED uniquement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

import stripe
from sqlalchemy.orm import Session

from app.config import Settings
from app.constants.subscription_plans import canonical_plan_code, get_plan, public_plan_code
from app.models.entreprise import Entreprise
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


def configure_stripe(settings: Settings) -> None:
    key = (settings.STRIPE_SECRET_KEY or "").strip()
    if not key:
        logger.warning(
            "Stripe indisponible : STRIPE_SECRET_KEY est vide dans backend/.env "
            "(utilisez une clé sk_test_… en développement)."
        )
        raise RuntimeError(
            "Stripe n’est pas configuré : ajoutez STRIPE_SECRET_KEY dans le fichier "
            "backend/.env (clé secrète du Dashboard Stripe, même mode test ou live que vos Price IDs)."
        )
    stripe.api_key = key


def _expected_price_env_names(plan_internal: str) -> tuple[str, str]:
    if plan_internal == "LIMITED":
        return ("STRIPE_PRICE_ID_LIMITED", "STRIPE_PRICE_ID_PACK_LIMITE")
    if plan_internal == "UNLIMITED":
        return ("STRIPE_PRICE_ID_UNLIMITED", "STRIPE_PRICE_ID_PACK_ILLIMITE")
    return ("STRIPE_PRICE_ID_LIMITED", "STRIPE_PRICE_ID_UNLIMITED")


def price_id_for_plan(settings: Settings, plan_code: str) -> str:
    code = canonical_plan_code((plan_code or "").strip().upper())
    if code not in ("LIMITED", "UNLIMITED"):
        raise ValueError("Seuls les packs LIMITED et UNLIMITED sont payants via Stripe.")
    mapping = {
        "LIMITED": (settings.STRIPE_PRICE_ID_LIMITED or "").strip(),
        "UNLIMITED": (settings.STRIPE_PRICE_ID_UNLIMITED or "").strip(),
    }
    pid = mapping.get(code, "")
    if not pid:
        a, b = _expected_price_env_names(code)
        logger.warning(
            "Stripe Checkout refusé : aucun Price ID pour le plan interne %r. "
            "Renseigner %s ou %s dans backend/.env (Price ID du prix récurrent, ex. price_…).",
            code,
            a,
            b,
        )
        raise RuntimeError(
            f"Stripe : aucun Price ID configuré pour ce pack. "
            f"Dans backend/.env, définissez {a} ou {b} avec l’identifiant du prix "
            f"(Dashboard → Produits → …), en mode test si vous utilisez sk_test_…."
        )
    if not pid.startswith("price_"):
        logger.warning(
            "Stripe : le Price ID pour %r ne ressemble pas à un id Stripe (attendu prefix price_): %r",
            code,
            pid[:24] + ("…" if len(pid) > 24 else ""),
        )
    return pid


def plan_code_from_price_id(settings: Settings, price_id: str) -> Optional[str]:
    pid = (price_id or "").strip()
    if not pid:
        return None
    if pid == (settings.STRIPE_PRICE_ID_LIMITED or "").strip():
        return "LIMITED"
    if pid == (settings.STRIPE_PRICE_ID_UNLIMITED or "").strip():
        return "UNLIMITED"
    return None


def _dt_from_unix(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def map_stripe_subscription_status(stripe_status: str) -> str:
    s = (stripe_status or "").strip().lower()
    if s in ("active", "trialing"):
        return "active"
    if s == "canceled":
        return "canceled"
    if s in ("incomplete", "incomplete_expired"):
        return "pending"
    if s in ("past_due", "unpaid"):
        return "expired"
    return "inactive"


def get_or_create_stripe_customer(db: Session, settings: Settings, entreprise: Entreprise) -> str:
    configure_stripe(settings)
    existing = (entreprise.stripe_customer_id or "").strip()
    if existing:
        return existing
    customer = stripe.Customer.create(
        email=entreprise.email_prof,
        name=entreprise.nom,
        metadata={"entreprise_id": str(entreprise.id)},
    )
    cid = customer["id"]
    entreprise.stripe_customer_id = cid
    db.add(entreprise)
    db.commit()
    db.refresh(entreprise)
    return cid


def create_checkout_session(
    db: Session,
    settings: Settings,
    entreprise: Entreprise,
    plan_code: str,
) -> Tuple[str, str]:
    configure_stripe(settings)
    code = canonical_plan_code(plan_code)
    if code == "TRIAL":
        raise ValueError("Le plan d’essai ne peut pas être souscrit via Stripe.")
    get_plan(code)
    price_id = price_id_for_plan(settings, code)
    customer_id = get_or_create_stripe_customer(db, settings, entreprise)

    logger.info(
        "STRIPE CHECKOUT create: entreprise_id=%s plan_internal=%s price_id_configured=%s (prefix %s…)",
        entreprise.id,
        code,
        bool((price_id or "").strip()),
        (price_id[:20] if len(price_id) > 20 else price_id),
    )

    base = (settings.FRONTEND_PUBLIC_URL or "http://localhost:8080").rstrip("/")
    # stripe_success=1 : le front appelle /confirm-checkout-session (fallback si webhook lent / local).
    success_url = (
        f"{base}/dashboard/pricing?checkout=success&stripe_success=1&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{base}/dashboard/pricing?checkout=cancel"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(entreprise.id),
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "entreprise_id": str(entreprise.id),
                "plan_code": code,
            },
            subscription_data={
                "metadata": {
                    "entreprise_id": str(entreprise.id),
                    "plan_code": code,
                }
            },
        )
    except stripe.InvalidRequestError as e:
        logger.error(
            "Stripe InvalidRequestError (checkout plan=%s price_id_prefix=%s): %s",
            code,
            (price_id[:16] + "…") if len(price_id) > 16 else price_id,
            getattr(e, "user_message", None) or str(e),
        )
        hint = (
            getattr(e, "user_message", None)
            or str(e)
            or "Vérifiez que le Price ID existe, est récurrent, et appartient au même compte Stripe que la clé secrète."
        )
        raise RuntimeError(
            f"Paiement Stripe : requête refusée. {hint} "
            f"(plan {code}, variable d’environnement {_expected_price_env_names(code)[0]})."
        ) from e
    except stripe.AuthenticationError as e:
        logger.error("Stripe AuthenticationError: %s", e)
        raise RuntimeError(
            "Stripe a refusé l’authentification : STRIPE_SECRET_KEY est invalide, révoquée, "
            "ou ne correspond pas au mode (test vs live) de vos Price IDs."
        ) from e
    except stripe.StripeError as e:
        logger.exception("Stripe erreur API lors de la création de session Checkout (plan=%s)", code)
        raise RuntimeError(
            getattr(e, "user_message", None)
            or "Erreur Stripe lors de la création de la session de paiement. Consultez les logs serveur."
        ) from e

    url = session.get("url") or ""
    sid = session.get("id") or ""
    if not url or not sid:
        raise RuntimeError("Réponse Stripe Checkout incomplète.")

    pending = Subscription(
        entreprise_id=entreprise.id,
        stripe_customer_id=customer_id,
        stripe_checkout_session_id=sid,
        plan_code=code,
        billing_cycle="monthly",
        status="pending",
        currency="mad",
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    logger.info(
        "STRIPE CHECKOUT: pending row id=%s checkout_session_id=%s",
        pending.id,
        sid,
    )

    return url, sid


def _cancel_other_active(db: Session, entreprise_id, keep_subscription_pk) -> None:
    q = db.query(Subscription).filter(
        Subscription.entreprise_id == entreprise_id,
        Subscription.status == "active",
    )
    if keep_subscription_pk:
        q = q.filter(Subscription.id != keep_subscription_pk)
    for row in q.all():
        row.status = "canceled"
        db.add(row)


def apply_subscription_payload_to_row(
    db: Session,
    settings: Settings,
    row: Subscription,
    sub_dict: Dict[str, Any],
    plan_fallback: Optional[str] = None,
) -> None:
    items = (sub_dict.get("items") or {}).get("data") or []
    price = (items[0].get("price") if items else None) or {}
    price_id = price.get("id")
    inferred = plan_code_from_price_id(settings, price_id) if price_id else None
    fb = canonical_plan_code(plan_fallback) if plan_fallback else None
    plan_code = inferred or fb or row.plan_code
    row.plan_code = canonical_plan_code(plan_code)

    recurring = price.get("recurring") or {}
    interval = recurring.get("interval") or "month"
    row.billing_cycle = str(interval).lower() if interval else "monthly"

    row.stripe_subscription_id = sub_dict.get("id") or row.stripe_subscription_id
    row.stripe_customer_id = sub_dict.get("customer") or row.stripe_customer_id
    row.status = map_stripe_subscription_status(sub_dict.get("status") or "")

    row.start_date = _dt_from_unix(sub_dict.get("current_period_start"))
    row.end_date = _dt_from_unix(sub_dict.get("current_period_end"))

    amt = price.get("unit_amount")
    if amt is not None:
        try:
            row.amount_cents = int(amt)
        except (TypeError, ValueError):
            pass
    cur = price.get("currency")
    if cur:
        row.currency = str(cur).lower()

    db.add(row)
    if row.status == "active":
        _cancel_other_active(db, row.entreprise_id, row.id)


def sync_subscription_from_stripe_obj(
    db: Session,
    settings: Settings,
    sub_dict: Dict[str, Any],
    *,
    checkout_session_id: Optional[str] = None,
    plan_from_metadata: Optional[str] = None,
) -> None:
    sub_id = sub_dict.get("id")
    if not sub_id:
        logger.warning("sync_subscription: objet subscription sans id")
        return

    meta = sub_dict.get("metadata") or {}
    ent_id = meta.get("entreprise_id")
    if not ent_id:
        cust = sub_dict.get("customer")
        if cust:
            ent = (
                db.query(Entreprise)
                .filter(Entreprise.stripe_customer_id == str(cust))
                .first()
            )
            if ent:
                ent_id = str(ent.id)
    if not ent_id:
        logger.warning(
            "sync_subscription: impossible de résoudre entreprise_id (subscription %s)",
            sub_id,
        )
        return

    try:
        ent_uuid = UUID(str(ent_id))
    except ValueError:
        logger.warning("sync_subscription: entreprise_id invalide %r", ent_id)
        return

    row: Optional[Subscription] = None
    if checkout_session_id:
        row = (
            db.query(Subscription)
            .filter(Subscription.stripe_checkout_session_id == checkout_session_id)
            .order_by(Subscription.created_at.desc())
            .first()
        )
    if row is None:
        row = db.query(Subscription).filter(Subscription.stripe_subscription_id == sub_id).first()
    if row is None:
        cust = sub_dict.get("customer")
        fb = canonical_plan_code(plan_from_metadata) if plan_from_metadata else "LIMITED"
        row = Subscription(
            entreprise_id=ent_uuid,
            stripe_customer_id=cust,
            stripe_subscription_id=sub_id,
            stripe_checkout_session_id=checkout_session_id,
            plan_code=fb,
            billing_cycle="monthly",
            status="pending",
            currency="mad",
        )
        db.add(row)
        db.flush()

    apply_subscription_payload_to_row(db, settings, row, sub_dict, plan_fallback=plan_from_metadata)
    logger.info(
        "DB SUBSCRIPTION pre-commit id=%s entreprise_id=%s plan_code=%s status=%s stripe_sub=%s",
        row.id,
        row.entreprise_id,
        row.plan_code,
        row.status,
        row.stripe_subscription_id,
    )
    db.commit()
    logger.info(
        "DB SUBSCRIPTION UPDATED (committed) id=%s plan_code=%s status=%s",
        row.id,
        row.plan_code,
        row.status,
    )


def refresh_subscription_row_from_api(db: Session, settings: Settings, subscription_id: str) -> None:
    configure_stripe(settings)
    sub = stripe.Subscription.retrieve(subscription_id)
    sync_subscription_from_stripe_obj(db, settings, dict(sub))


def handle_checkout_session_completed(db: Session, settings: Settings, session: Dict[str, Any]) -> None:
    configure_stripe(settings)
    logger.info("CHECKOUT SESSION COMPLETED HANDLER START")
    meta = session.get("metadata") or {}
    entreprise_id = meta.get("entreprise_id")
    plan_code = meta.get("plan_code")
    checkout_sid = session.get("id")
    logger.info("SESSION ID %s", checkout_sid)
    logger.info("METADATA %s", meta)
    logger.info("ENTREPRISE_ID (metadata) %s", entreprise_id)
    logger.info("PLAN_CODE (metadata) %s", plan_code)
    sub_id = session.get("subscription")
    logger.info("SUBSCRIPTION_ID (session) %s", sub_id)
    if not sub_id:
        logger.warning("checkout.session.completed sans subscription: %s", checkout_sid)
        return
    sub = stripe.Subscription.retrieve(str(sub_id))
    sub_dict = dict(sub)
    # Renfort : métadonnées session (Checkout) parfois plus fiables que la souscription seule.
    sm = dict(sub_dict.get("metadata") or {})
    if entreprise_id and not sm.get("entreprise_id"):
        sm["entreprise_id"] = str(entreprise_id)
    if plan_code and not sm.get("plan_code"):
        sm["plan_code"] = str(plan_code)
    sub_dict["metadata"] = sm
    sync_subscription_from_stripe_obj(
        db,
        settings,
        sub_dict,
        checkout_session_id=checkout_sid,
        plan_from_metadata=plan_code,
    )
    logger.info("CHECKOUT SESSION COMPLETED HANDLER END session_id=%s", checkout_sid)


def confirm_checkout_session_for_entreprise(
    db: Session,
    settings: Settings,
    entreprise: Entreprise,
    session_id: str,
) -> Dict[str, Any]:
    """
    Synchronise l’abonnement local après un paiement Checkout réussi (webhook inatteignable en local / lent).
    """
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id requis.")
    configure_stripe(settings)
    logger.info("CONFIRM CHECKOUT START session_id=%s entreprise_id=%s", sid, entreprise.id)

    session = stripe.checkout.Session.retrieve(
        sid,
        expand=["subscription", "line_items"],
    )
    meta = dict(session.get("metadata") or {})
    meta_ent = meta.get("entreprise_id")
    plan_m = meta.get("plan_code")
    pay_status = session.get("payment_status")
    sub_field = session.get("subscription")

    logger.info(
        "CONFIRM CHECKOUT session payment_status=%s subscription=%s metadata=%s",
        pay_status,
        sub_field if sub_field is None or isinstance(sub_field, str) else "expanded",
        meta,
    )
    if str(meta_ent or "") != str(entreprise.id):
        raise ValueError("Cette session de paiement ne correspond pas à votre compte entreprise.")

    if pay_status not in ("paid", "no_payment_required") and not sub_field:
        raise ValueError(
            f"Paiement non finalisé (payment_status={pay_status!r}, pas d’abonnement).",
        )
    if not sub_field:
        raise ValueError("Session sans abonnement associé — réessayez ou contactez le support.")

    if isinstance(sub_field, str):
        sub_id = sub_field
    else:
        sub_id = (sub_field.get("id") or "") if isinstance(sub_field, dict) else getattr(
            sub_field, "id", str(sub_field)
        )

    sub = stripe.Subscription.retrieve(str(sub_id))
    sub_dict = dict(sub)
    sm = dict(sub_dict.get("metadata") or {})
    if meta_ent and not sm.get("entreprise_id"):
        sm["entreprise_id"] = str(meta_ent)
    if plan_m and not sm.get("plan_code"):
        sm["plan_code"] = str(plan_m)
    sub_dict["metadata"] = sm

    cs_id = session.get("id")
    sync_subscription_from_stripe_obj(
        db,
        settings,
        sub_dict,
        checkout_session_id=cs_id,
        plan_from_metadata=plan_m,
    )
    row = (
        db.query(Subscription)
        .filter(Subscription.stripe_checkout_session_id == cs_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not row:
        row = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == str(sub_id))
            .first()
        )
    if not row:
        raise RuntimeError("Synchronisation locale incomplète après confirmation Stripe.")
    return {
        "ok": True,
        "plan_code": public_plan_code(row.plan_code),
        "status": row.status,
        "subscription_id": str(row.id),
    }


def handle_invoice_payment_succeeded(db: Session, settings: Settings, invoice: Dict[str, Any]) -> None:
    configure_stripe(settings)
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    refresh_subscription_row_from_api(db, settings, sub_id)


def handle_invoice_payment_failed(db: Session, settings: Settings, invoice: Dict[str, Any]) -> None:
    configure_stripe(settings)
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    refresh_subscription_row_from_api(db, settings, sub_id)
