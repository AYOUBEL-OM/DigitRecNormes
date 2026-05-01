import { isAxiosError } from "axios";

import { api } from "@/services/axios";

function stripeCheckoutErrorMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const raw = err.response?.data as { detail?: unknown } | undefined;
    const d = raw?.detail;
    if (typeof d === "string" && d.trim()) return d.trim();
    if (Array.isArray(d)) {
      const parts = d.map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg?: string }).msg) : String(x)));
      const joined = parts.filter(Boolean).join(" ");
      if (joined.trim()) return joined.trim();
    }
    if (err.response?.status === 503) {
      return "Service Stripe indisponible ou configuration incomplète (voir le message du serveur ci-dessus).";
    }
  }
  if (err instanceof Error && err.message.trim()) return err.message.trim();
  return "Vérifiez backend/.env : STRIPE_SECRET_KEY (sk_test_…) et les Price IDs des packs (STRIPE_PRICE_ID_LIMITED / STRIPE_PRICE_ID_UNLIMITED), en mode test.";
}

export type SubscriptionPlan = {
  code: string;
  label: string;
  price: number;
  currency: string;
  billing_note?: string | null;
  payment_required?: boolean;
  is_trial?: boolean;
  features: string[];
  limits: Record<string, unknown>;
};

export type SubscriptionMe = {
  has_active_subscription: boolean;
  /** ESSAI_GRATUIT | PACK_LIMITE | PACK_ILLIMITE */
  plan_code: string | null;
  plan_label: string | null;
  status: string | null;
  billing_cycle: string | null;
  end_date: string | null;
  start_date: string | null;
  currency: string | null;
  amount_cents: number | null;
  max_active_offers: number | null;
  active_offers_count: number;
  offers_remaining: number | null;
  payment_required: boolean;
  is_trial: boolean;
  trial_exhausted: boolean;
  offers_used: number;
  offers_limit: number | null;
  can_create_offer: boolean;
  message?: string | null;
};

export async function fetchSubscriptionPlans(): Promise<SubscriptionPlan[]> {
  const { data } = await api.get<SubscriptionPlan[]>("/api/subscriptions/plans");
  return Array.isArray(data) ? data : [];
}

export async function fetchSubscriptionMe(): Promise<SubscriptionMe> {
  const { data } = await api.get<SubscriptionMe>("/api/subscriptions/me");
  return data;
}

export async function createCheckoutSession(planCode: string): Promise<{
  checkout_url: string;
  session_id: string;
}> {
  try {
    const { data } = await api.post<{ checkout_url: string; session_id: string }>(
      "/api/subscriptions/create-checkout-session",
      { plan_code: planCode },
    );
    return data;
  } catch (e) {
    throw new Error(stripeCheckoutErrorMessage(e));
  }
}

export type ConfirmCheckoutResponse = {
  ok: boolean;
  plan_code: string;
  status: string;
  subscription_id: string;
};

export async function confirmCheckoutSession(sessionId: string): Promise<ConfirmCheckoutResponse> {
  try {
    const { data } = await api.post<ConfirmCheckoutResponse>(
      "/api/subscriptions/confirm-checkout-session",
      { session_id: sessionId },
    );
    return data;
  } catch (e) {
    throw new Error(stripeCheckoutErrorMessage(e));
  }
}
