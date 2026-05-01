import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import RolePage from "@/components/RolePage";
import {
  getCandidatures,
  getOffresEntreprise,
  getCandidatureDetails,
  resolveApiAssetUrl,
  type EntrepriseCandidatureItem,
  type OffreEntrepriseItem,
  type CandidatureDetailsResponse,
} from "@/services/authService";
import { BookOpen, ExternalLink, FileText, Mail, Search } from "lucide-react";
import CandidateEmailDialog from "@/components/entreprise/CandidateEmailDialog";
import OralReportDialog from "@/oral-interview/components/OralReportDialog";
import WrittenReportDialog from "@/components/Quiz/WrittenReportDialog";

const STATUT_LABELS: Record<string, string> = {
  nouvelle: "En attente",
  en_cours: "En cours",
  acceptee: "Acceptée",
  refusee: "Refusée",
  a_revoir: "À revoir",
};

const ALL_OFFERS = "__all__";

function statutBadgeClass(statut: string): string {
  switch (statut) {
    case "acceptee":
      return "border-transparent bg-emerald-500/15 text-emerald-800 dark:text-emerald-300";
    case "refusee":
      return "border-transparent bg-destructive/15 text-destructive";
    case "a_revoir":
      return "border-transparent bg-amber-500/15 text-amber-950 dark:text-amber-100";
    case "en_cours":
    case "nouvelle":
    default:
      return "border-transparent bg-blue-500/15 text-blue-800 dark:text-blue-300";
  }
}

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Normalise un score brut (0–5 ou 0–100) vers un pourcentage d'affichage 0–100. */
function scoreToPercent(raw: number | null | undefined): number | null {
  if (raw == null || Number.isNaN(Number(raw))) return null;
  const v = Number(raw);
  if (v <= 5) return Math.round((v / 5) * 100);
  return Math.min(100, Math.round(v));
}

/** Liste : score_ia est sur 5 (API). */
function listCvPercent(scoreIa: number | null): string | null {
  if (scoreIa == null) return null;
  return `${scoreToPercent(scoreIa)}%`;
}

/** Score affiché en liste : moyenne des épreuves disponibles, sinon repli sur le % CV seul. */
function listDisplayedPercent(c: EntrepriseCandidatureItem): string | null {
  if (c.score_final_pct != null && Number.isFinite(Number(c.score_final_pct))) {
    return `${Math.round(Number(c.score_final_pct))}%`;
  }
  return listCvPercent(c.score_ia);
}

function ScoreBlock({
  label,
  raw,
  pendingLabel,
}: {
  label: string;
  raw: number | null;
  pendingLabel: string;
}) {
  const pct = scoreToPercent(raw);
  const hasValue = pct != null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {hasValue ? `${pct}%` : pendingLabel}
        </span>
      </div>
      {hasValue ? (
        <Progress value={pct} className="h-2.5" />
      ) : (
        <div className="h-2.5 w-full rounded-full bg-muted/80" />
      )}
    </div>
  );
}

const CandidatesInner = () => {
  const [rows, setRows] = useState<EntrepriseCandidatureItem[]>([]);
  const [offers, setOffers] = useState<OffreEntrepriseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [offersLoading, setOffersLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [offerFilter, setOfferFilter] = useState<string>(ALL_OFFERS);

  const [detailId, setDetailId] = useState<string | null>(null);
  const [peekName, setPeekName] = useState<string | null>(null);
  const [details, setDetails] = useState<CandidatureDetailsResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [writtenReportOpen, setWrittenReportOpen] = useState(false);
  const [oralReportOpen, setOralReportOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  /** Cible de portail à l’intérieur du Sheet : les modales imbriquées restent dans l’arbre DOM du Dialog Radix (modal stable, pas de « outside » fantôme). */
  const [nestedModalHost, setNestedModalHost] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      const { data, error: err } = await getCandidatures();
      if (cancelled) return;
      if (err) {
        setError(err.message);
        setRows([]);
      } else {
        setRows(data ?? []);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setOffersLoading(true);
      const { data } = await getOffresEntreprise();
      if (cancelled) return;
      const list = data ?? [];
      setOffers(list.filter((o) => (o.status ?? "active") === "active"));
      setOffersLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!detailId) {
      setDetails(null);
      setDetailError(null);
      return;
    }
    setDetails(null);
    setDetailError(null);
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      const { data, error: err } = await getCandidatureDetails(detailId);
      if (cancelled) return;
      if (err) {
        setDetailError(err.message);
        setDetails(null);
      } else {
        setDetails(data ?? null);
      }
      setDetailLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [detailId]);

  useEffect(() => {
    if (!detailId) {
      setWrittenReportOpen(false);
      setOralReportOpen(false);
      setEmailDialogOpen(false);
    }
  }, [detailId]);

  const filtered = useMemo(() => {
    let list = rows;
    if (offerFilter !== ALL_OFFERS) {
      list = list.filter((r) => r.offre_id === offerFilter);
    }
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((r) => {
      const name = (r.candidat_nom || "").toLowerCase();
      const titre = (r.offre_titre || "").toLowerCase();
      return name.includes(q) || titre.includes(q);
    });
  }, [rows, query, offerFilter]);

  const openDetail = (id: string, listName: string) => {
    setPeekName(listName);
    setDetailId(id);
  };

  const detailName = details
    ? `${details.candidate.prenom} ${details.candidate.nom}`.trim()
    : peekName ?? "";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Candidats</h1>
        <p className="text-sm text-muted-foreground">
          {loading
            ? "Chargement…"
            : `${filtered.length} affiché${filtered.length === 1 ? "" : "s"}${
                offerFilter !== ALL_OFFERS || query.trim()
                  ? ` (${rows.length} au total)`
                  : ""
              }`}
        </p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <div className="space-y-2 sm:w-72">
          <label className="text-xs font-medium text-muted-foreground">
            Filtrer par offre
          </label>
          <Select
            value={offerFilter}
            onValueChange={setOfferFilter}
            disabled={loading || offersLoading}
          >
            <SelectTrigger>
              <SelectValue placeholder="Choisir une offre" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_OFFERS}>Toutes les offres</SelectItem>
              {offers.map((o) => (
                <SelectItem key={o.id} value={o.id}>
                  {o.title || "Sans titre"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="relative max-w-md flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Rechercher par nom ou intitulé du poste…"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={loading}
          />
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : null}

      {!loading && !error && filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {query.trim() || offerFilter !== ALL_OFFERS
            ? "Aucun candidat ne correspond aux filtres."
            : "Aucune candidature pour vos offres pour le moment."}
        </p>
      ) : null}

      <div className="grid gap-3">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex animate-pulse items-center gap-4 rounded-xl border bg-card p-4"
              >
                <div className="h-10 w-10 rounded-full bg-muted" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-40 rounded bg-muted" />
                  <div className="h-3 w-56 rounded bg-muted/80" />
                </div>
                <div className="h-6 w-20 rounded-full bg-muted" />
                <div className="h-4 w-10 rounded bg-muted" />
              </div>
            ))
          : filtered.map((c) => (
              <button
                type="button"
                key={c.id}
                onClick={() => openDetail(c.id, c.candidat_nom)}
                className="flex w-full cursor-pointer items-center gap-4 rounded-xl border bg-card p-4 text-left card-shadow transition-all hover:card-shadow-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Avatar className="h-10 w-10 shrink-0">
                  <AvatarFallback className="bg-accent/10 text-sm font-medium text-accent">
                    {initialsFromName(c.candidat_nom)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-foreground">{c.candidat_nom}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {c.offre_titre || "—"}
                  </p>
                </div>
                <Badge className={statutBadgeClass(c.statut_synthese ?? c.statut)}>
                  {STATUT_LABELS[c.statut_synthese ?? c.statut] ??
                    (c.statut_synthese ?? c.statut)}
                </Badge>
                <div className="shrink-0 text-sm font-medium tabular-nums text-foreground">
                  {listDisplayedPercent(c) ?? "—"}
                </div>
              </button>
            ))}
      </div>

      <Sheet
        open={!!detailId}
        onOpenChange={(open) => {
          if (!open) {
            setWrittenReportOpen(false);
            setOralReportOpen(false);
            setEmailDialogOpen(false);
            setDetailId(null);
            setPeekName(null);
          }
        }}
      >
        <SheetContent
          side="right"
          className="flex w-full flex-col overflow-y-auto sm:max-w-lg"
          onPointerDownOutside={(e) => {
            if (writtenReportOpen || oralReportOpen || emailDialogOpen) {
              e.preventDefault();
            }
          }}
          onFocusOutside={(e) => {
            if (writtenReportOpen || oralReportOpen || emailDialogOpen) {
              e.preventDefault();
            }
          }}
          onInteractOutside={(e) => {
            if (writtenReportOpen || oralReportOpen || emailDialogOpen) {
              e.preventDefault();
            }
          }}
          onEscapeKeyDown={(e) => {
            if (writtenReportOpen) {
              e.preventDefault();
              setWrittenReportOpen(false);
              return;
            }
            if (oralReportOpen) {
              e.preventDefault();
              setOralReportOpen(false);
              return;
            }
            if (emailDialogOpen) {
              e.preventDefault();
              setEmailDialogOpen(false);
            }
          }}
        >
            {detailId ? (
              <motion.div
                key={detailId}
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                className="relative flex flex-1 flex-col gap-6"
              >
                <div
                  ref={setNestedModalHost}
                  className="pointer-events-none absolute left-0 top-0 z-[240] h-px w-px overflow-visible"
                  aria-hidden
                />
                <SheetHeader className="text-left">
                  <div className="flex items-start gap-4">
                    <Avatar className="h-14 w-14">
                      <AvatarFallback className="bg-accent/15 text-lg font-semibold text-accent">
                        {initialsFromName(detailName || peekName || "?")}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1 space-y-1">
                      <SheetTitle className="text-xl leading-tight">
                        {detailLoading && !details
                          ? peekName || "Chargement…"
                          : detailName || "Candidat"}
                      </SheetTitle>
                      <SheetDescription className="line-clamp-2">
                        {details?.offre_titre || "—"}
                      </SheetDescription>
                    </div>
                  </div>
                </SheetHeader>

                {detailError ? (
                  <p className="text-sm text-destructive">{detailError}</p>
                ) : null}

                {detailLoading && !details ? (
                  <div className="space-y-4 animate-pulse">
                    <div className="h-24 rounded-xl bg-muted" />
                    <div className="h-24 rounded-xl bg-muted" />
                  </div>
                ) : null}

                {details ? (
                  <>
                    <div className="rounded-xl border bg-card/50 p-4">
                      <h3 className="mb-4 text-sm font-semibold tracking-tight text-foreground">
                        Scores
                      </h3>
                      <div className="space-y-5">
                        {details.scores.score_final_percent != null &&
                        Number.isFinite(details.scores.score_final_percent) ? (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between gap-3 text-sm">
                              <span className="font-medium text-foreground">Score final</span>
                              <span className="tabular-nums font-semibold text-foreground">
                                {Math.round(details.scores.score_final_percent)}%
                              </span>
                            </div>
                            <Progress
                              value={Math.min(
                                100,
                                Math.max(0, details.scores.score_final_percent),
                              )}
                              className="h-2.5"
                            />
                          </div>
                        ) : null}
                        <ScoreBlock
                          label="Correspondance CV"
                          raw={details.scores.score_cv_matching}
                          pendingLabel="N/A"
                        />
                        <ScoreBlock
                          label="Test écrit"
                          raw={details.scores.score_ecrit}
                          pendingLabel="En attente"
                        />
                        <ScoreBlock
                          label="Test oral"
                          raw={details.scores.score_oral}
                          pendingLabel="En attente"
                        />
                      </div>
                    </div>

                    <Button
                      size="lg"
                      className="w-full gap-2"
                      disabled={!resolveApiAssetUrl(details.candidate.cv_url)}
                      onClick={() => {
                        const url = resolveApiAssetUrl(details.candidate.cv_url);
                        if (url) {
                          window.open(url, "_blank", "noopener,noreferrer");
                        }
                      }}
                    >
                      Visualiser le CV
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                    {!resolveApiAssetUrl(details.candidate.cv_url) ? (
                      <p className="text-center text-xs text-muted-foreground">
                        CV indisponible : fichier absent sur ce serveur (base importée sans les
                        fichiers, ou chemin obsolète).
                      </p>
                    ) : null}

                    <Button
                      type="button"
                      variant="outline"
                      size="lg"
                      className="w-full gap-2"
                      disabled={details.scores.score_ecrit == null}
                      onClick={() => setWrittenReportOpen(true)}
                    >
                      Voir le rapport écrit
                      <BookOpen className="h-4 w-4" />
                    </Button>
                    {details.scores.score_ecrit == null ? (
                      <p className="text-center text-xs text-muted-foreground">
                        Rapport disponible après passage du test écrit.
                      </p>
                    ) : null}

                    <Button
                      type="button"
                      variant="outline"
                      size="lg"
                      className="w-full gap-2"
                      disabled={details.scores.score_oral == null}
                      onClick={() => setOralReportOpen(true)}
                    >
                      Voir le rapport oral
                      <FileText className="h-4 w-4" />
                    </Button>
                    {details.scores.score_oral == null ? (
                      <p className="text-center text-xs text-muted-foreground">
                        Rapport disponible après passage du test oral (score enregistré).
                      </p>
                    ) : null}

                    <Button
                      type="button"
                      variant="secondary"
                      size="lg"
                      className="w-full gap-2"
                      disabled={!details.candidate.email?.trim()}
                      onClick={() => setEmailDialogOpen(true)}
                    >
                      Envoyer email
                      <Mail className="h-4 w-4" />
                    </Button>
                    {!details.candidate.email?.trim() ? (
                      <p className="text-center text-xs text-muted-foreground">
                        Aucune adresse email enregistrée pour ce candidat.
                      </p>
                    ) : null}

                    <Separator />

                    <div className="space-y-3">
                      <h3 className="text-sm font-semibold text-foreground">
                        Informations
                      </h3>
                      <dl className="space-y-2 text-sm">
                        <div className="flex justify-between gap-4">
                          <dt className="text-muted-foreground">Email</dt>
                          <dd className="text-right font-medium text-foreground">
                            {details.candidate.email}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4">
                          <dt className="text-muted-foreground">CIN</dt>
                          <dd className="text-right font-medium text-foreground">
                            {details.candidate.cin?.trim() || "—"}
                          </dd>
                        </div>
                        {details.status.etape_actuelle ? (
                          <div className="flex justify-between gap-4">
                            <dt className="text-muted-foreground">Étape</dt>
                            <dd className="text-right font-medium text-foreground">
                              {details.status.etape_actuelle}
                            </dd>
                          </div>
                        ) : null}
                        <div className="flex justify-between gap-4">
                          <dt className="text-muted-foreground">Statut</dt>
                          <dd className="text-right">
                            <Badge
                              className={statutBadgeClass(
                                details.status.statut_synthese ?? details.status.statut,
                              )}
                            >
                              {STATUT_LABELS[
                                details.status.statut_synthese ?? details.status.statut
                              ] ??
                                (details.status.statut_synthese ?? details.status.statut)}
                            </Badge>
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </>
                ) : null}
              </motion.div>
            ) : null}
        </SheetContent>
      </Sheet>

      {detailId && details ? (
        <CandidateEmailDialog
          open={emailDialogOpen}
          onOpenChange={setEmailDialogOpen}
          candidatureId={detailId}
          details={details}
          portalContainer={nestedModalHost}
        />
      ) : null}

      {detailId ? (
        <>
          <WrittenReportDialog
            open={writtenReportOpen}
            onOpenChange={setWrittenReportOpen}
            candidatureId={detailId}
            candidateLabel={detailName || peekName || "Candidat"}
            portalContainer={nestedModalHost}
          />
          <OralReportDialog
            open={oralReportOpen}
            onOpenChange={setOralReportOpen}
            candidatureId={detailId}
            candidateLabel={detailName || peekName || "Candidat"}
            portalContainer={nestedModalHost}
          />
        </>
      ) : null}
    </div>
  );
};

const Candidates = () => (
  <RolePage allow={["company"]}>
    {() => <CandidatesInner />}
  </RolePage>
);

export default Candidates;
