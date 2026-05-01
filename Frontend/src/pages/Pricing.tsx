import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useAccount } from "@/hooks/useAccount";
import {
  confirmCheckoutSession,
  createCheckoutSession,
  fetchSubscriptionMe,
  fetchSubscriptionPlans,
  type SubscriptionMe,
  type SubscriptionPlan,
} from "@/services/subscriptionService";

export default function Pricing() {
  const { account } = useAccount();
  const isCompany = account?.accountType === "company";
  const [searchParams, setSearchParams] = useSearchParams();

  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [me, setMe] = useState<SubscriptionMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkoutPlan, setCheckoutPlan] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await fetchSubscriptionPlans();
      setPlans(p);
      if (isCompany) {
        const m = await fetchSubscriptionMe();
        setMe(m);
      } else {
        setMe(null);
      }
    } catch (e) {
      console.error(e);
      toast.error("Impossible de charger les formules.");
    } finally {
      setLoading(false);
    }
  }, [isCompany]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    const stripeSuccess = searchParams.get("stripe_success");
    const sessionId = searchParams.get("session_id");

    const clearCheckoutParams = () => {
      const next = new URLSearchParams(searchParams);
      next.delete("checkout");
      next.delete("session_id");
      next.delete("stripe_success");
      setSearchParams(next, { replace: true });
    };

    // Priorité : synchroniser côté API (webhook local souvent absent) avant de vider l’URL.
    if (stripeSuccess === "1" && sessionId) {
      void (async () => {
        try {
          await confirmCheckoutSession(sessionId);
          await load();
          toast.success("Abonnement activé", {
            description: "Votre formule est en place. Vous pouvez publier de nouvelles offres.",
          });
        } catch (e) {
          console.error(e);
          await load();
          toast.error("Activation de l’abonnement", {
            description:
              e instanceof Error && e.message.trim()
                ? e.message.trim()
                : "Paiement reçu : réessayez ou contactez le support si le pack n’apparaît pas.",
          });
        } finally {
          clearCheckoutParams();
        }
      })();
      return;
    }

    if (checkout === "success") {
      toast.success("Paiement confirmé", {
        description: "Mise à jour de votre abonnement…",
      });
      void load();
      clearCheckoutParams();
      return;
    }
    if (checkout === "cancel") {
      toast.message("Paiement annulé", {
        description: "Vous pouvez choisir une autre formule quand vous voulez.",
      });
      clearCheckoutParams();
    }
  }, [searchParams, setSearchParams, load]);

  const onSubscribe = async (code: string) => {
    if (!isCompany) {
      toast.error("Connectez-vous avec un compte entreprise pour souscrire.");
      return;
    }
    setCheckoutPlan(code);
    try {
      const { checkout_url } = await createCheckoutSession(code);
      if (checkout_url) {
        window.location.href = checkout_url;
        return;
      }
      toast.error("URL de paiement indisponible.");
    } catch (e: unknown) {
      console.error(e);
      const description =
        e instanceof Error && e.message.trim()
          ? e.message.trim()
          : "Vérifiez backend/.env (STRIPE_SECRET_KEY et Price IDs en mode test).";
      toast.error("Impossible de démarrer le paiement.", { description });
    } finally {
      setCheckoutPlan(null);
    }
  };

  const trialPlan = plans.find((p) => p.is_trial);
  const paidPlans = plans.filter((p) => p.payment_required);

  return (
    <div className="mx-auto max-w-5xl space-y-10 px-4 py-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Formules</h1>
        <p className="mt-2 text-muted-foreground">
          1 offre gratuite à l&apos;inscription, puis abonnement mensuel (Stripe, mode test) pour créer
          davantage d&apos;offres selon le pack choisi.
        </p>
        {isCompany && me?.has_active_subscription ? (
          <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-sm">
            <Sparkles className="h-4 w-4 text-amber-500" />
            <span>
              Formule actuelle : <strong>{me.plan_label ?? me.plan_code}</strong>
              {me.status ? ` — ${me.status}` : null}
            </span>
          </p>
        ) : null}
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="h-10 w-10 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-3">
          {trialPlan ? (
            <div className="flex flex-col rounded-xl border-2 border-dashed border-border bg-card/80 p-6 card-shadow">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-xl font-semibold text-foreground">{trialPlan.label}</h2>
                <span className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  Par défaut
                </span>
              </div>
              <p className="mt-3 text-3xl font-bold text-foreground">0 MAD</p>
              <p className="text-sm text-muted-foreground">À l&apos;inscription, sans carte bancaire</p>
              <ul className="mt-6 flex-1 space-y-2 text-sm text-muted-foreground">
                {trialPlan.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Button className="mt-8 w-full" variant="outline" disabled>
                Inclus à l&apos;inscription
              </Button>
            </div>
          ) : null}

          {paidPlans.map((plan) => {
            const isCurrent =
              isCompany &&
              me?.has_active_subscription &&
              me.plan_code?.toUpperCase() === plan.code.toUpperCase();
            const busy = checkoutPlan === plan.code;
            const highlight = plan.code === "PACK_ILLIMITE";
            return (
              <div
                key={plan.code}
                className={`flex flex-col rounded-xl border-2 bg-card p-6 card-shadow transition-shadow ${
                  highlight ? "border-primary/40 shadow-md" : "border-border"
                }`}
              >
                <h2 className="text-xl font-semibold text-foreground">{plan.label}</h2>
                <div className="mt-3">
                  <span className="text-3xl font-bold text-foreground">
                    {plan.price.toLocaleString("fr-FR")}
                  </span>
                  <span className="ml-1 text-sm font-normal text-muted-foreground">
                    {plan.currency.toUpperCase()} / mois
                  </span>
                </div>
                <ul className="mt-6 flex-1 space-y-2 text-sm text-muted-foreground">
                  {plan.features.map((f) => (
                    <li key={f} className="flex gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-8 flex flex-col gap-2">
                  <Button
                    className="w-full"
                    variant={highlight ? "default" : "secondary"}
                    disabled={!isCompany || isCurrent || busy}
                    onClick={() => onSubscribe(plan.code)}
                  >
                    {busy ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Redirection…
                      </>
                    ) : isCurrent ? (
                      "Votre formule"
                    ) : (
                      "Payer avec Stripe"
                    )}
                  </Button>
                  {!isCompany ? (
                    <p className="text-center text-xs text-muted-foreground">
                      Connexion entreprise requise pour payer.
                    </p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-center text-xs text-muted-foreground">
        Paiement sécurisé par Stripe Checkout (cartes de test en développement).
      </p>
    </div>
  );
}
