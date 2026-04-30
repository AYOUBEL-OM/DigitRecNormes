import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Users, Briefcase, CalendarCheck, TrendingUp, CreditCard } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNavigate } from "react-router-dom";
import { useAccount } from "@/hooks/useAccount";
import {
  getDashboardStats,
  type DashboardStatsResponse,
} from "@/services/authService";
import { fetchSubscriptionMe, type SubscriptionMe } from "@/services/subscriptionService";

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.5, ease: "easeOut" as const },
  }),
};

const Dashboard = () => {
  const navigate = useNavigate();
  const { account } = useAccount();
  const isCompany = account?.accountType === "company";

  const [stats, setStats] = useState<DashboardStatsResponse | null>(null);
  const [loading, setLoading] = useState(isCompany);
  const [error, setError] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionMe | null>(null);

  const loadStats = async () => {
    setLoading(true);
    setError(null);
    const { data, error: err } = await getDashboardStats();
    if (err) {
      setError(err.message);
      setStats(null);
    } else {
      setStats(data ?? null);
    }
    if (isCompany) {
      try {
        setSubscription(await fetchSubscriptionMe());
      } catch {
        setSubscription(null);
      }
    }
    setLoading(false);
  };

  useEffect(() => {
    if (!isCompany) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      await loadStats();
    })();
    const onProfile = () => {
      if (!cancelled) loadStats();
    };
    window.addEventListener("digitrec:session-update", onProfile);
    return () => {
      cancelled = true;
      window.removeEventListener("digitrec:session-update", onProfile);
    };
  }, [isCompany]);

  const statCards = useMemo(() => {
    if (!isCompany || !stats) return null;
    return [
      {
        label: "Total Candidats",
        value: stats.total_candidats,
        icon: Users,
        color: "text-accent",
        hint: "Candidatures liées à vos offres",
      },
      {
        label: "Offres Actives",
        value: stats.offres_actives,
        icon: Briefcase,
        color: "text-success",
        hint: "Offres au statut actif",
      },
      {
        label: "Entretiens prévus",
        value: stats.entretiens_prevus,
        icon: CalendarCheck,
        color: "text-warning",
        hint: "Étapes Oral ou Entretien",
      },
      {
        label: "Taux de conversion",
        value: `${stats.taux_conversion}%`,
        icon: TrendingUp,
        color: "text-accent",
        hint: "Candidatures acceptées / total",
      },
    ];
  }, [isCompany, stats]);

  const pipelines = stats?.recrutements_en_cours ?? [];

  const quotaLine = (() => {
    if (!subscription?.has_active_subscription) return null;
    const used = subscription.offers_used ?? subscription.active_offers_count ?? 0;
    const lim = subscription.offers_limit ?? subscription.max_active_offers;
    if (subscription.is_trial && lim != null) {
      const suffix = used > 1 ? "offres utilisées" : "offre utilisée";
      return `Essai gratuit : ${used} / ${lim} ${suffix}`;
    }
    if (lim == null) {
      return `Pack illimité : ${used} offre(s) active(s)`;
    }
    return `${subscription.plan_label ?? "Pack limité"} : ${used} / ${lim} offre(s) active(s)`;
  })();

  const canCreate =
    !isCompany ||
    (subscription != null &&
      subscription.has_active_subscription === true &&
      subscription.can_create_offer !== false);
  const createBlockedReason =
    subscription?.message?.trim() ||
    "Vous avez utilisé votre offre gratuite. Veuillez choisir un pack pour créer de nouvelles offres.";

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Tableau de bord</h1>
          {isCompany && (account?.displayName || stats?.nom_entreprise) ? (
            <p className="mt-1 text-lg font-semibold text-foreground">
              {account?.displayName || stats?.nom_entreprise}
            </p>
          ) : null}
          <p className="text-sm text-muted-foreground">
            Vue d&apos;ensemble de votre activité de recrutement
          </p>
        </div>
        {isCompany ? (
          canCreate ? (
            <Button onClick={() => navigate("/dashboard/new-offer")}>+ Nouvelle offre</Button>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <Button disabled className="pointer-events-none opacity-60">
                    + Nouvelle offre
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-xs text-center">
                {createBlockedReason}
              </TooltipContent>
            </Tooltip>
          )
        ) : null}
      </div>

      {!isCompany ? (
        <p className="text-sm text-muted-foreground">
          Bienvenue dans votre espace personnel.
        </p>
      ) : null}

      {error && isCompany ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : null}

      {isCompany ? (
        <motion.div
          initial="hidden"
          animate="visible"
          variants={fadeUp}
          custom={0}
          className="flex flex-col gap-3 rounded-xl border bg-card p-5 card-shadow sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-secondary p-2.5 text-accent">
              <CreditCard className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Abonnement</p>
              {subscription?.has_active_subscription ? (
                <div className="mt-1 space-y-1 text-sm text-muted-foreground">
                  <p>
                    <span className="font-semibold text-foreground">
                      Plan actuel : {subscription.plan_label ?? subscription.plan_code}
                    </span>
                    {subscription.status ? ` · ${subscription.status}` : null}
                  </p>
                  {quotaLine ? <p>{quotaLine}</p> : null}
                  {subscription.payment_required && subscription.end_date ? (
                    <p>
                      Fin de période :{" "}
                      {new Date(subscription.end_date).toLocaleDateString("fr-FR")}
                    </p>
                  ) : null}
                  {!subscription.can_create_offer && subscription.message ? (
                    <p className="font-medium text-amber-700 dark:text-amber-400">
                      {subscription.message}
                    </p>
                  ) : subscription.trial_exhausted ? (
                    <p className="font-medium text-amber-700 dark:text-amber-400">
                      Vous avez utilisé votre offre gratuite. Veuillez choisir un pack pour continuer.
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">
                  Aucune formule active — contactez le support ou reconnectez-vous.
                </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col gap-2 sm:items-end">
            <Button variant="outline" onClick={() => navigate("/dashboard/pricing")}>
              {!subscription?.can_create_offer && subscription?.is_trial
                ? "Choisir un pack"
                : subscription?.trial_exhausted
                  ? "Choisir un pack"
                  : subscription?.has_active_subscription
                    ? "Formules et paiement"
                    : "Voir les formules"}
            </Button>
          </div>
        </motion.div>
      ) : null}

      {isCompany ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {loading && !statCards
            ? Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-xl border bg-card p-5 card-shadow"
                >
                  <div className="h-24 rounded-lg bg-muted" />
                </div>
              ))
            : null}
          {statCards
            ? statCards.map((stat, i) => (
                <motion.div
                  key={stat.label}
                  initial="hidden"
                  animate="visible"
                  variants={fadeUp}
                  custom={i}
                  className="rounded-xl border bg-card p-5 card-shadow transition-all hover:card-shadow-hover"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">{stat.label}</p>
                      <p className="mt-1 text-3xl font-bold text-foreground">{stat.value}</p>
                    </div>
                    <div className={`rounded-lg bg-secondary p-2.5 ${stat.color}`}>
                      <stat.icon className="h-5 w-5" />
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground/80">{stat.hint}</span>
                  </p>
                </motion.div>
              ))
            : null}
        </div>
      ) : null}

      {isCompany ? (
        <motion.div initial="hidden" animate="visible" variants={fadeUp} custom={4}>
          <h2 className="mb-4 text-lg font-semibold text-foreground">Recrutements en cours</h2>
          {loading ? (
            <p className="text-sm text-muted-foreground">Chargement…</p>
          ) : pipelines.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucune offre active pour le moment.</p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {pipelines.map((p, i) => (
                <motion.div
                  key={`${p.title}-${i}`}
                  initial="hidden"
                  animate="visible"
                  variants={fadeUp}
                  custom={5 + i}
                  className="rounded-xl border bg-card p-5 card-shadow"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="font-medium text-foreground">{p.title}</h3>
                    <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                      {p.count_candidats} candidat{p.count_candidats === 1 ? "" : "s"}
                    </span>
                  </div>
                  <Progress value={p.progression} className="mb-2 h-2" />
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{p.stage}</span>
                    <span className="font-medium">{p.progression}%</span>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </motion.div>
      ) : null}
    </div>
  );
};

export default Dashboard;
