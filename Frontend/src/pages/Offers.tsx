import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import RolePage from "../components/RolePage";
import "../styles/workspace.css";
import { ApiError, apiFetch, clearAuthStorage } from "@/services/authService";
import { fetchSubscriptionMe, type SubscriptionMe } from "@/services/subscriptionService";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useToast } from "@/hooks/use-toast";
import {
  OFFER_EXPERIENCE_LEVELS,
  isValidOfferExperienceLevel,
  normalizeStoredLevel,
} from "@/constants/offerExperienceLevel";
import { Copy, ExternalLink, Loader2 } from "lucide-react";

const editOfferSelectClassName =
  "flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

export type OffreEntreprise = {
  id: string;
  title?: string | null;
  profile?: string | null;
  localisation?: string | null;
  type_contrat?: string | null;
  level?: string | null;
  nombre_candidats_recherche?: number | null;
  nombre_experience_minimun?: number | null;
  niveau_etude?: string | null;
  competences?: string | null;
  type_examens_ecrit?: string | null;
  nombre_questions_orale?: number | null;
  date_fin_offres?: string | null;
  description_postes?: string | null;
  status?: string | null;
  token_liens?: string | null;
  lien_candidature?: string | null;
  created_at?: string | null;
  lien_public_actif?: boolean;
  affichage_statut?: string | null;
};

const actionButtonBase: React.CSSProperties = {
  borderRadius: "10px",
  padding: "10px 16px",
  fontSize: "14px",
  fontWeight: 600,
  cursor: "pointer",
  transition: "all 0.2s ease",
  border: "1px solid transparent",
  background: "transparent",
};

function formatDateFr(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString("fr-FR");
}

/** Affichage « Expire le : … » sur la carte */
function formatExpireLe(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
}

export type OfferUiState = "inactive" | "expired" | "active";

export type OfferFilter = "all" | "active" | "inactive" | "expired";

/** `status` désactivé manuellement en base */
export function isOfferInactive(offer: OffreEntreprise): boolean {
  return (offer.status || "").trim().toLowerCase() === "inactive";
}

/** Date de fin strictement dans le passé (sans nouveau statut DB). */
export function isOfferExpired(offer: OffreEntreprise): boolean {
  if (!offer.date_fin_offres?.trim()) return false;
  const end = new Date(offer.date_fin_offres);
  if (Number.isNaN(end.getTime())) return false;
  return end.getTime() < Date.now();
}

/** Priorité affichage / filtres : Inactive → Expirée → Active (calcul client). */
export function getOfferUiState(offer: OffreEntreprise): OfferUiState {
  if (isOfferInactive(offer)) return "inactive";
  if (isOfferExpired(offer)) return "expired";
  return "active";
}

function matchesOfferFilter(offer: OffreEntreprise, f: OfferFilter): boolean {
  switch (f) {
    case "all":
      return true;
    case "active":
      return getOfferUiState(offer) === "active";
    case "inactive":
      return isOfferInactive(offer);
    case "expired":
      return isOfferExpired(offer);
    default:
      return true;
  }
}

function applyUrlPublic(offer: OffreEntreprise): string {
  if (offer.lien_candidature?.trim()) return offer.lien_candidature.trim();
  const tok = offer.token_liens?.trim();
  if (!tok) return "";
  if (typeof window !== "undefined") return `${window.location.origin}/apply/${tok}`;
  return "";
}

function statutListeLabel(offer: OffreEntreprise): { label: string; tone: "ok" | "warn" | "off" } {
  const st = getOfferUiState(offer);
  if (st === "inactive") return { label: "Inactive", tone: "off" };
  if (st === "expired") return { label: "Expirée", tone: "warn" };
  return { label: "Active", tone: "ok" };
}

function statutBadgeStyle(tone: "ok" | "warn" | "off"): React.CSSProperties {
  if (tone === "warn")
    return {
      borderRadius: "999px",
      padding: "10px 18px",
      fontWeight: 600,
      background: "#FFF7ED",
      color: "#C2410C",
      border: "1px solid #FDBA74",
    };
  if (tone === "off")
    return {
      borderRadius: "999px",
      padding: "10px 18px",
      fontWeight: 600,
      background: "#F8FAFC",
      color: "#64748B",
      border: "1px solid #FECDD3",
    };
  return {
    borderRadius: "999px",
    padding: "10px 18px",
    fontWeight: 600,
    background: "#ECFDF5",
    color: "#047857",
    border: "1px solid #A7F3D0",
  };
}

function toDatetimeLocalValue(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Texte compétences pour l’édition : évite un textarea vide si le GET détail omet ou vide le champ alors que liste / détail l’ont déjà. */
function resolveCompetencesForEdit(
  fromApi: OffreEntreprise,
  id: string,
  detail: OffreEntreprise | null,
  liste: OffreEntreprise[],
): string {
  const nonEmpty = (v: string | null | undefined) =>
    v != null && String(v).trim() !== "" ? String(v) : null;

  const fromList = liste.find((x) => String(x.id) === String(id));
  return (
    nonEmpty(fromApi.competences) ??
    (detail && String(detail.id) === String(id) ? nonEmpty(detail.competences) : null) ??
    nonEmpty(fromList?.competences) ??
    (fromApi.competences != null ? String(fromApi.competences) : "")
  );
}

const OffersInner = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [offres, setOffres] = useState<OffreEntreprise[]>([]);
  const [loading, setLoading] = useState(true);
  const [offerFilter, setOfferFilter] = useState<OfferFilter>("all");
  const [subscription, setSubscription] = useState<SubscriptionMe | null>(null);

  const canCreateOffer =
    subscription != null &&
    subscription.has_active_subscription === true &&
    subscription.can_create_offer !== false;
  const createBlockedHint =
    subscription?.message?.trim() ||
    "Vous avez utilisé votre offre gratuite. Veuillez choisir un pack pour créer de nouvelles offres.";

  const handleAuthFailure = useCallback(
    (err: unknown) => {
      const message = err instanceof Error ? err.message : "";
      const status = err instanceof ApiError ? err.status : undefined;
      const isAuthError =
        status === 401 ||
        /token invalide|expir/i.test(message) ||
        /authentification requise/i.test(message);

      if (!isAuthError) return false;

      clearAuthStorage("entreprise");
      toast({
        title: "Session expirée",
        description: "Merci de vous reconnecter à votre compte entreprise.",
        variant: "destructive",
      });
      navigate("/login", { replace: true });
      return true;
    },
    [navigate, toast],
  );

  const filteredOffres = useMemo(
    () => offres.filter((o) => matchesOfferFilter(o, offerFilter)),
    [offres, offerFilter],
  );

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailOffer, setDetailOffer] = useState<OffreEntreprise | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm, setEditForm] = useState({
    title: "",
    profile: "",
    localisation: "",
    type_contrat: "",
    level: "",
    nombre_candidats_recherche: "",
    nombre_experience_minimun: "",
    niveau_etude: "",
    competences: "",
    type_examens_ecrit: "",
    nombre_questions_orale: "",
    date_fin_offres: "",
    description_postes: "",
  });
  const [editingId, setEditingId] = useState<string | null>(null);

  const fetchOffres = useCallback(async () => {
    const data = (await apiFetch("/api/offres")) as OffreEntreprise[];
    setOffres(Array.isArray(data) ? data : []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        try {
          const me = await fetchSubscriptionMe();
          if (!cancelled) setSubscription(me);
        } catch {
          if (!cancelled) setSubscription(null);
        }
        await fetchOffres();
      } catch (err) {
        if (!handleAuthFailure(err)) {
          console.error("Erreur chargement offres:", err);
          toast({
            title: "Erreur",
            description: err instanceof Error ? err.message : "Chargement impossible",
            variant: "destructive",
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchOffres, handleAuthFailure, toast]);

  const openDetail = async (id: string) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailOffer(null);
    try {
      const o = (await apiFetch(`/api/offres/${encodeURIComponent(id)}`)) as OffreEntreprise;
      setDetailOffer(o);
    } catch (e) {
      if (handleAuthFailure(e)) return;
      toast({
        title: "Impossible de charger l’offre",
        description: e instanceof Error ? e.message : "Erreur réseau",
        variant: "destructive",
      });
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const openEdit = async (id: string) => {
    setEditingId(id);
    setEditOpen(true);
    setEditSaving(false);
    try {
      const o = (await apiFetch(`/api/offres/${encodeURIComponent(id)}`)) as OffreEntreprise;
      setEditForm({
        title: o.title ?? "",
        profile: o.profile ?? "",
        localisation: o.localisation ?? "",
        type_contrat: o.type_contrat ?? "",
        level:
          normalizeStoredLevel(o.level) ||
          normalizeStoredLevel(o.niveau_etude),
        nombre_candidats_recherche:
          o.nombre_candidats_recherche != null ? String(o.nombre_candidats_recherche) : "",
        nombre_experience_minimun:
          o.nombre_experience_minimun != null ? String(o.nombre_experience_minimun) : "",
        niveau_etude: o.niveau_etude ?? "",
        competences: resolveCompetencesForEdit(o, id, detailOffer, offres),
        type_examens_ecrit: o.type_examens_ecrit ?? "",
        nombre_questions_orale:
          o.nombre_questions_orale != null ? String(o.nombre_questions_orale) : "",
        date_fin_offres: toDatetimeLocalValue(o.date_fin_offres ?? undefined),
        description_postes: o.description_postes ?? "",
      });
    } catch (e) {
      if (handleAuthFailure(e)) return;
      toast({
        title: "Chargement impossible",
        description: e instanceof Error ? e.message : "",
        variant: "destructive",
      });
      setEditOpen(false);
    }
  };

  const saveEdit = async () => {
    if (!editingId) return;
    const levelTrim = editForm.level.trim();
    if (
      !editForm.title.trim() ||
      !editForm.description_postes.trim() ||
      !levelTrim ||
      !isValidOfferExperienceLevel(levelTrim)
    ) {
      toast({
        title: "Champs requis",
        description:
          "Titre, description et un niveau d’expérience (Junior, Confirmé ou Senior) sont obligatoires.",
        variant: "destructive",
      });
      return;
    }
    setEditSaving(true);
    try {
      const payload: Record<string, unknown> = {
        title: editForm.title.trim(),
        profile: editForm.profile.trim() || null,
        localisation: editForm.localisation.trim() || null,
        type_contrat: editForm.type_contrat.trim() || null,
        level: levelTrim,
        nombre_candidats_recherche: editForm.nombre_candidats_recherche
          ? Number(editForm.nombre_candidats_recherche)
          : null,
        nombre_experience_minimun: editForm.nombre_experience_minimun
          ? Number(editForm.nombre_experience_minimun)
          : null,
        niveau_etude: editForm.niveau_etude.trim() || null,
        competences: editForm.competences.trim() || null,
        type_examens_ecrit: editForm.type_examens_ecrit.trim() || null,
        nombre_questions_orale: editForm.nombre_questions_orale
          ? Number(editForm.nombre_questions_orale)
          : null,
        date_fin_offres: editForm.date_fin_offres
          ? new Date(editForm.date_fin_offres).toISOString()
          : null,
        description_postes: editForm.description_postes.trim(),
      };
      await apiFetch(`/api/offres/${encodeURIComponent(editingId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast({ title: "Offre mise à jour" });
      setEditOpen(false);
      setEditingId(null);
      await fetchOffres();
      if (detailOffer?.id === editingId) {
        const o = (await apiFetch(`/api/offres/${encodeURIComponent(editingId)}`)) as OffreEntreprise;
        setDetailOffer(o);
      }
    } catch (e) {
      if (handleAuthFailure(e)) return;
      toast({
        title: "Erreur",
        description: e instanceof Error ? e.message : "Enregistrement impossible",
        variant: "destructive",
      });
    } finally {
      setEditSaving(false);
    }
  };

  const confirmDeactivate = async (id: string, title: string) => {
    if (
      !window.confirm(
        `Désactiver l’offre « ${title || "Sans titre"} » ? Elle restera visible ici, mais le lien public de candidature ne fonctionnera plus. Les candidatures déjà reçues sont conservées.`,
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/api/offres/${encodeURIComponent(id)}`, { method: "DELETE" });
      toast({ title: "Offre désactivée" });
      setDetailOpen(false);
      setDetailOffer(null);
      await fetchOffres();
    } catch (e) {
      if (handleAuthFailure(e)) return;
      toast({
        title: "Désactivation impossible",
        description: e instanceof Error ? e.message : "",
        variant: "destructive",
      });
    }
  };

  const copyLink = (offer: OffreEntreprise) => {
    if (offer.lien_public_actif === false) {
      toast({
        title: "Lien inactif",
        description: "Cette offre est désactivée ou expirée : le lien public ne peut pas être utilisé.",
        variant: "destructive",
      });
      return;
    }
    const url = applyUrlPublic(offer);
    if (!url) {
      toast({ title: "Lien indisponible", variant: "destructive" });
      return;
    }
    void navigator.clipboard.writeText(url).then(
      () => toast({ title: "Lien copié dans le presse-papiers" }),
      () => toast({ title: "Copie impossible", variant: "destructive" }),
    );
  };

  const detailUrl = detailOffer ? applyUrlPublic(detailOffer) : "";
  const detailLienActif = detailOffer ? detailOffer.lien_public_actif !== false : false;

  return (
    <>
      <div className="legacy-workspace">
        <section className="legacy-workspace__hero">
          <div>
            <div className="legacy-workspace__eyebrow">Espace entreprise</div>
            <div className="flex items-center justify-between">
              <h1 className="legacy-workspace__title">Mes offres</h1>
            </div>
            <p className="legacy-workspace__subtitle">
              Retrouvez ici vos offres publiées, leur état et leurs informations essentielles.
            </p>
            {!loading && subscription && !canCreateOffer ? (
              <p
                style={{
                  marginTop: "12px",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: "#B45309",
                  maxWidth: "640px",
                }}
              >
                {subscription.message?.trim() ||
                  "Vous avez utilisé votre offre gratuite. Veuillez choisir un pack pour créer de nouvelles offres."}{" "}
                <button
                  type="button"
                  onClick={() => navigate("/dashboard/pricing")}
                  style={{
                    textDecoration: "underline",
                    fontWeight: 700,
                    color: "#1D4ED8",
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                  }}
                >
                  Voir les tarifs
                </button>
              </p>
            ) : null}
          </div>
          {!loading ? (
            <div style={{ marginTop: "16px" }}>
              {canCreateOffer ? (
                <Button type="button" onClick={() => navigate("/dashboard/new-offer")} className="rounded-full">
                  + Nouvelle offre
                </Button>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex">
                      <Button type="button" disabled className="rounded-full opacity-60">
                        + Nouvelle offre
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs text-center">
                    {createBlockedHint}
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
          ) : null}
        </section>

        {!loading && offres.length > 0 ? (
          <section
            className="legacy-workspace__stack"
            style={{ marginBottom: "8px", paddingBottom: 0 }}
          >
            <div className="flex items-center justify-between gap-4" style={{ marginBottom: "12px" }}>
              <p
                style={{
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "#64748B",
                  marginBottom: 0,
                }}
              >
                Filtrer
              </p>
              {canCreateOffer ? (
                <Button type="button" onClick={() => navigate("/dashboard/new-offer")} className="rounded-full">
                  + Nouvelle offre
                </Button>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex">
                      <Button type="button" disabled className="rounded-full opacity-60">
                        + Nouvelle offre
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-xs text-center">
                    {createBlockedHint}
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {(
                [
                  { id: "all" as const, label: "Tous" },
                  { id: "active" as const, label: "Actives" },
                  { id: "inactive" as const, label: "Inactives" },
                  { id: "expired" as const, label: "Expirées" },
                ] as const
              ).map((tab) => {
                const selected = offerFilter === tab.id;
                return (
                  <Button
                    key={tab.id}
                    type="button"
                    size="sm"
                    variant={selected ? "default" : "outline"}
                    className="rounded-full"
                    onClick={() => setOfferFilter(tab.id)}
                  >
                    {tab.label}
                  </Button>
                );
              })}
            </div>
          </section>
        ) : null}

        <section className="legacy-workspace__stack">
          {loading ? (
            <p>Chargement...</p>
          ) : offres.length === 0 ? (
            <p>Aucune offre pour le moment.</p>
          ) : filteredOffres.length === 0 ? (
            <p style={{ color: "#64748B" }}>Aucune offre ne correspond à ce filtre.</p>
          ) : (
            filteredOffres.map((offer) => (
              <article
                key={offer.id}
                className="legacy-workspace__panel"
                style={{
                  borderRadius: "28px",
                  padding: "30px 30px 24px",
                  boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
                }}
              >
                <div
                  className="legacy-workspace__panel-header"
                  style={{ alignItems: "flex-start", marginBottom: "24px" }}
                >
                  <div>
                    <h2
                      style={{
                        fontSize: "24px",
                        lineHeight: 1.2,
                        marginBottom: "8px",
                      }}
                    >
                      {offer.title || "Sans titre"}
                    </h2>
                    <span
                      style={{
                        fontSize: "15px",
                        color: "#64748B",
                        display: "inline-block",
                      }}
                    >
                      {offer.profile || "Profil non renseigné"}
                    </span>
                    {offer.date_fin_offres ? (
                      <p
                        style={{
                          fontSize: "13px",
                          color: "#64748B",
                          marginTop: "10px",
                        }}
                      >
                        Expire le : {formatExpireLe(offer.date_fin_offres)}
                      </p>
                    ) : null}
                  </div>

                  <div
                    className="legacy-workspace__badges"
                    style={{ gap: "10px", flexWrap: "wrap" }}
                  >
                    {(() => {
                      const sv = statutListeLabel(offer);
                      return (
                        <span className="legacy-workspace__badge" style={statutBadgeStyle(sv.tone)}>
                          {sv.label}
                        </span>
                      );
                    })()}

                    {offer.type_contrat ? (
                      <span
                        className="legacy-workspace__badge"
                        style={{
                          borderRadius: "999px",
                          padding: "10px 18px",
                          fontWeight: 600,
                        }}
                      >
                        {offer.type_contrat}
                      </span>
                    ) : null}
                  </div>
                </div>

                <div
                  className="legacy-workspace__meta-grid"
                  style={{ marginBottom: "20px" }}
                >
                  <div>
                    <div className="legacy-workspace__label">Niveau requis</div>
                    <div className="legacy-workspace__value">{offer.level || "-"}</div>
                  </div>

                  <div>
                    <div className="legacy-workspace__label">Candidats recherchés</div>
                    <div className="legacy-workspace__value">
                      {offer.nombre_candidats_recherche ?? "-"}
                    </div>
                  </div>

                  <div>
                    <div className="legacy-workspace__label">Localisation</div>
                    <div className="legacy-workspace__value">{offer.localisation || "-"}</div>
                  </div>

                  <div>
                    <div className="legacy-workspace__label">Niveau d’études</div>
                    <div className="legacy-workspace__value">{offer.niveau_etude || "-"}</div>
                  </div>
                </div>

                {offer.competences && (
                  <div style={{ marginTop: "8px", marginBottom: "22px" }}>
                    <div
                      className="legacy-workspace__label"
                      style={{ marginBottom: "10px" }}
                    >
                      Compétences requises
                    </div>

                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: "8px",
                      }}
                    >
                      {offer.competences.split(",").map((c, i) => (
                        <span
                          key={i}
                          style={{
                            background: "#EEF2FF",
                            color: "#3730A3",
                            padding: "7px 12px",
                            borderRadius: "999px",
                            fontSize: "13px",
                            fontWeight: 500,
                          }}
                        >
                          {c.trim()}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "16px",
                    flexWrap: "wrap",
                    borderTop: "1px solid #E2E8F0",
                    paddingTop: "18px",
                    marginTop: "8px",
                  }}
                >
                  <div
                    style={{
                      fontSize: "13px",
                      color: "#64748B",
                    }}
                  >
                    Gestion de l’offre
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: "10px",
                      flexWrap: "wrap",
                    }}
                  >
                    <button
                      type="button"
                      style={{
                        ...actionButtonBase,
                        background: "#F8FAFC",
                        border: "1px solid #E2E8F0",
                        color: "#0F172A",
                      }}
                      onClick={() => void openDetail(offer.id)}
                    >
                      Voir détail
                    </button>

                    <button
                      type="button"
                      style={{
                        ...actionButtonBase,
                        background: "#EFF6FF",
                        border: "1px solid #BFDBFE",
                        color: "#1D4ED8",
                      }}
                      onClick={() => void openEdit(offer.id)}
                    >
                      Modifier
                    </button>

                    {!isOfferInactive(offer) ? (
                      <button
                        type="button"
                        style={{
                          ...actionButtonBase,
                          background: "#FEF2F2",
                          border: "1px solid #FECACA",
                          color: "#DC2626",
                        }}
                        onClick={() => void confirmDeactivate(offer.id, offer.title || "")}
                      >
                        Désactiver
                      </button>
                    ) : null}
                  </div>
                </div>
              </article>
            ))
          )}
        </section>
      </div>

      <Sheet open={detailOpen} onOpenChange={setDetailOpen}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Détail de l’offre</SheetTitle>
            <SheetDescription>
              Informations complètes et lien public de candidature (token stable).
            </SheetDescription>
          </SheetHeader>
          {detailLoading ? (
            <div className="flex items-center gap-2 py-8 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              Chargement…
            </div>
          ) : detailOffer ? (
            <div className="mt-6 space-y-5 text-sm">
              <div className="rounded-xl border bg-muted/30 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Lien de candidature
                </p>
                {!detailLienActif ? (
                  <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-950 dark:text-amber-100">
                    Ce lien n’est plus actif pour les candidats (offre désactivée ou date de fin dépassée). Le
                    token reste inchangé à titre d’historique.
                  </p>
                ) : null}
                <p className="mt-2 break-all font-mono text-xs text-foreground">{detailUrl || "—"}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={!detailUrl || !detailLienActif}
                    onClick={() => copyLink(detailOffer)}
                  >
                    <Copy className="mr-2 h-4 w-4" />
                    Copier le lien
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!detailUrl || !detailLienActif}
                    onClick={() => detailUrl && window.open(detailUrl, "_blank", "noopener,noreferrer")}
                  >
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Ouvrir
                  </Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Token stocké :{" "}
                  <span className="font-mono">{detailOffer.token_liens ?? "—"}</span>
                </p>
              </div>

              <dl className="grid gap-3">
                <DetailRow label="Titre" value={detailOffer.title} />
                <DetailRow label="Profil" value={detailOffer.profile} />
                <DetailRow label="Type de contrat" value={detailOffer.type_contrat} />
                <DetailRow label="Localisation" value={detailOffer.localisation} />
                <DetailRow label="Niveau d’études" value={detailOffer.niveau_etude} />
                <DetailRow label="Niveau requis (exp.)" value={detailOffer.level} />
                <DetailRow
                  label="Années d’expérience min."
                  value={
                    detailOffer.nombre_experience_minimun != null
                      ? String(detailOffer.nombre_experience_minimun)
                      : undefined
                  }
                />
                <DetailRow
                  label="Nombre de candidats recherchés"
                  value={
                    detailOffer.nombre_candidats_recherche != null
                      ? String(detailOffer.nombre_candidats_recherche)
                      : undefined
                  }
                />
                <DetailRow
                  label="Nombre de questions orales"
                  value={
                    detailOffer.nombre_questions_orale != null
                      ? String(detailOffer.nombre_questions_orale)
                      : undefined
                  }
                />
                <DetailRow label="Type examen écrit" value={detailOffer.type_examens_ecrit} />
                <DetailRow
                  label="Date fin d’offre"
                  value={formatDateFr(detailOffer.date_fin_offres ?? undefined)}
                />
                <DetailRow
                  label="État (vue recrutement)"
                  value={
                    statutListeLabel(detailOffer).label +
                    (detailOffer.status ? ` (status DB : ${detailOffer.status})` : "")
                  }
                />
                <DetailRow
                  label="Création"
                  value={formatDateFr(detailOffer.created_at ?? undefined)}
                />
              </dl>
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Description</p>
                <p className="whitespace-pre-wrap rounded-lg border bg-card p-3 text-foreground">
                  {detailOffer.description_postes || "—"}
                </p>
              </div>
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Compétences requises</p>
                <p className="whitespace-pre-wrap rounded-lg border bg-card p-3 text-foreground">
                  {detailOffer.competences || "—"}
                </p>
              </div>
              <div className="flex gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => void openEdit(detailOffer.id)}>
                  Modifier cette offre
                </Button>
                {!isOfferInactive(detailOffer) ? (
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={() => void confirmDeactivate(detailOffer.id, detailOffer.title || "")}
                  >
                    Désactiver
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      <Sheet
        open={editOpen}
        onOpenChange={(o) => {
          setEditOpen(o);
          if (!o) setEditingId(null);
        }}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Modifier l’offre</SheetTitle>
            <SheetDescription>
              Le lien public et le token de candidature ne changent pas lors de l’enregistrement.
            </SheetDescription>
          </SheetHeader>
          <div className="mt-6 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-title">Intitulé du poste *</Label>
              <Input
                id="edit-title"
                placeholder="Ex. Responsable marketing, Comptable, Développeur web"
                value={editForm.title}
                onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-profile">Profil</Label>
              <Input
                id="edit-profile"
                placeholder="Ex. Profil junior en marketing digital, Comptable confirmé, Développeur Full Stack"
                value={editForm.profile}
                onChange={(e) => setEditForm((f) => ({ ...f, profile: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-loc">Localisation</Label>
                <Input
                  id="edit-loc"
                  placeholder="Ex. Casablanca, Rabat, Hybride, Remote"
                  value={editForm.localisation}
                  onChange={(e) => setEditForm((f) => ({ ...f, localisation: e.target.value }))}
                  disabled={editSaving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-contrat">Type de contrat</Label>
                <Input
                  id="edit-contrat"
                  value={editForm.type_contrat}
                  onChange={(e) => setEditForm((f) => ({ ...f, type_contrat: e.target.value }))}
                  disabled={editSaving}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-level">Niveau requis *</Label>
              <select
                id="edit-level"
                value={editForm.level}
                onChange={(e) => setEditForm((f) => ({ ...f, level: e.target.value }))}
                className={editOfferSelectClassName}
                disabled={editSaving}
                required
              >
                <option value="">Sélectionner un niveau d’expérience</option>
                {OFFER_EXPERIENCE_LEVELS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-nb">Candidats recherchés</Label>
                <Input
                  id="edit-nb"
                  type="number"
                  min={0}
                  value={editForm.nombre_candidats_recherche}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, nombre_candidats_recherche: e.target.value }))
                  }
                  disabled={editSaving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-exp">Expérience min. (années)</Label>
                <Input
                  id="edit-exp"
                  type="number"
                  min={0}
                  value={editForm.nombre_experience_minimun}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, nombre_experience_minimun: e.target.value }))
                  }
                  disabled={editSaving}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-ne">Niveau d’études</Label>
              <Input
                id="edit-ne"
                value={editForm.niveau_etude}
                onChange={(e) => setEditForm((f) => ({ ...f, niveau_etude: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-comp">Compétences (texte ou liste séparée par des virgules)</Label>
              <Textarea
                id="edit-comp"
                rows={3}
                value={editForm.competences}
                onChange={(e) => setEditForm((f) => ({ ...f, competences: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="edit-exam">Type examen écrit</Label>
                <Input
                  id="edit-exam"
                  value={editForm.type_examens_ecrit}
                  onChange={(e) => setEditForm((f) => ({ ...f, type_examens_ecrit: e.target.value }))}
                  disabled={editSaving}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-nq">Questions orales (nombre)</Label>
                <Input
                  id="edit-nq"
                  type="number"
                  min={0}
                  value={editForm.nombre_questions_orale}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, nombre_questions_orale: e.target.value }))
                  }
                  disabled={editSaving}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-df">Date / heure fin d’offre</Label>
              <Input
                id="edit-df"
                type="datetime-local"
                value={editForm.date_fin_offres}
                onChange={(e) => setEditForm((f) => ({ ...f, date_fin_offres: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-desc">Description *</Label>
              <Textarea
                id="edit-desc"
                rows={6}
                placeholder="Ex. Décrivez les missions, les responsabilités, le périmètre (équipe, clients, outils), les objectifs du poste et les conditions particulières (déplacements, horaires, etc.)."
                value={editForm.description_postes}
                onChange={(e) => setEditForm((f) => ({ ...f, description_postes: e.target.value }))}
                disabled={editSaving}
              />
            </div>
            <div className="flex justify-end gap-2 pt-4">
              <Button type="button" variant="outline" disabled={editSaving} onClick={() => setEditOpen(false)}>
                Annuler
              </Button>
              <Button type="button" disabled={editSaving} onClick={() => void saveEdit()}>
                {editSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Enregistrer"}
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:justify-between sm:gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground sm:text-right">{value?.trim() ? value : "—"}</dd>
    </div>
  );
}

const Offers = () => (
  <RolePage allow={["company"]}>
    {() => <OffersInner />}
  </RolePage>
);

export default Offers;
