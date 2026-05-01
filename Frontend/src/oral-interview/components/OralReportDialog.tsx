import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, Mic, X, FileDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getApiBaseUrl, resolveApiAssetUrl, apiFetch, getAccessToken, ApiError } from "@/services/authService";
import {
  ENABLE_ADVANCED_METRICS,
  confidenceDisplayLabel,
  oralReportParseScore,
  phoneSignalPhrase,
  stressDisplayLabel,
} from "@/constants/reportDisplayMetrics";

type OralReportQuestion = {
  question_order: number;
  question_text: string | null;
  transcript_text: string | null;
  audio_url: string | null;
  answer_duration_seconds: number | null;
  relevance_score: number | null;
  hesitation_score: number | null;
  coherence_score?: number | null;
  composite_quality_score?: number | null;
  quality_label: string;
};

type OralReportPayload = {
  candidature_id: string;
  offre_titre: string | null;
  test_oral: Record<string, unknown> | null;
  questions: OralReportQuestion[];
  cheating_flags: unknown;
  timeline: Array<{
    time_display: string;
    label_fr: string;
    type: string;
    detail?: unknown;
  }>;
  primary_snapshot_url: string | null;
  /** Photo avant entretien ; prioritaire sur les snapshots. */
  candidate_photo_url?: string | null;
  candidate_image_url?: string | null;
  badge: {
    badge_key?: string;
    badge_display?: string;
    source?: string;
    synthesis_badge_key?: string;
  } | null;
  ai_summary: string;
  ai_report?: {
    visual_behavior?: string;
    stress_assessment?: string;
    confidence_assessment?: string;
    suspicion_assessment?: string;
    conclusion?: string;
    strengths?: string[];
    weaknesses?: string[];
    recommendation?: string;
    decision_reason?: string;
    risk_notes?: string;
  };
  proctoring_insights?: {
    gaze_stability?: string;
    dominant_direction?: string;
    gaze_professional?: string;
    gaze_explanation?: string;
    gaze_score?: number | null;
    movement_level?: string;
    movement_professional?: string;
    movement_explanation?: string;
    movement_score?: number | null;
    head_movement?: string;
    head_yaw?: number | null;
    head_pitch?: number | null;
    presence_stability?: string;
    presence_professional?: string;
    presence_explanation?: string;
    presence_score?: number | null;
    suspicion_level?: string;
    suspicion_professional?: string;
    suspicion_score?: number | null;
    suspicion_signals?: unknown;
    signals?: Record<string, unknown>;
  };
  behavioral_analysis?: {
    visual?: string;
    stress?: string;
    confidence?: string;
    suspicion?: string;
  };
};

function qualityTone(label: string): "good" | "mid" | "bad" {
  if (label === "bonne") return "good";
  if (label === "moyenne") return "mid";
  return "bad";
}

function qualityClass(tone: "good" | "mid" | "bad"): string {
  if (tone === "good") return "border-success/40 bg-success/10 text-foreground";
  if (tone === "mid") return "border-warning/50 bg-warning/15 text-foreground";
  return "border-destructive/40 bg-destructive/10 text-destructive";
}

function initialsFromLabel(label: string | null | undefined) {
  const s = String(label || "").trim();
  if (!s) return "—";
  const parts = s.split(/\s+/).filter(Boolean);
  const a = parts[0]?.[0] || "";
  const b = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : "";
  const out = (a + b).toUpperCase();
  return out || "—";
}

function suggestedFilenameFromContentDisposition(cd: string | null, fallback: string): string {
  if (!cd) return fallback;
  const star = /filename\*=UTF-8''([^;\s]+)/i.exec(cd);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].replace(/^"+|"+$/g, ""));
    } catch {
      /* ignore */
    }
  }
  const quoted = /filename="([^"]+)"/i.exec(cd);
  if (quoted?.[1]) return quoted[1].trim();
  const plain = /filename=([^;\s]+)/i.exec(cd);
  if (plain?.[1]) return plain[1].trim().replace(/^"+|"+$/g, "");
  return fallback;
}

async function downloadPdf(candidatureId: string) {
  const token = getAccessToken("entreprise");
  const url = `${getApiBaseUrl()}/api/oral/results/${encodeURIComponent(candidatureId)}/pdf`;
  console.log("PDF request start", { url, hasToken: Boolean(token) });
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    console.log("PDF response status", res.status);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    const fallbackName = `rapport_oral_${candidatureId}.pdf`;
    a.download = suggestedFilenameFromContentDisposition(res.headers.get("Content-Disposition"), fallbackName);
    a.click();
    URL.revokeObjectURL(objUrl);
  } catch (e) {
    // "Failed to fetch" = erreur réseau / CORS / mixed-content: inclure l’URL dans le message.
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Téléchargement PDF impossible (${url}). ${msg}`);
  }
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidatureId: string;
  candidateLabel: string;
  /** Si fourni (ex. nœud dans le Sheet candidat), le portail s’y attache pour rester dans l’arbre du Dialog Radix. */
  portalContainer?: HTMLElement | null;
};

const OralReportDialog = ({
  open,
  onOpenChange,
  candidatureId,
  candidateLabel,
  portalContainer,
}: Props) => {
  console.log("[ORAL REPORT DEBUG] render", { open, candidatureId });
  const [data, setData] = useState<OralReportPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  const loadReport = useCallback(async () => {
    console.log("[ORAL REPORT DEBUG] loadReport called");
    setLoading(true);
    setError(null);
    try {
      const endpoint = `/api/oral/results/${encodeURIComponent(candidatureId)}`;
      const finalUrl = `${getApiBaseUrl()}${endpoint}`;
      console.log("[ORAL REPORT] candidatureId:", candidatureId);
      console.log("[ORAL REPORT] final URL:", finalUrl);

      // Health check simple avant le report (évite le "Failed to fetch" opaque)
      try {
        const healthUrl = `${getApiBaseUrl()}/sante`;
        const h = await fetch(healthUrl, { method: "GET" });
        if (!h.ok) {
          throw new Error(`Backend health check failed (HTTP ${h.status})`);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        throw new Error(`Backend inaccessible (${getApiBaseUrl()}). ${msg}`);
      }

      // Utiliser le client API central (même pattern dashboard entreprise)
      let res: OralReportPayload;
      try {
        res = (await apiFetch(endpoint, {
          method: "GET",
          auth: "entreprise",
        })) as OralReportPayload;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        const isNetwork =
          msg.toLowerCase().includes("failed to fetch") ||
          msg.toLowerCase().includes("networkerror") ||
          msg.toLowerCase().includes("load failed");
        // Fallback temporaire demandé : retry 1x avec fetch natif + Bearer entreprise.
        if (isNetwork) {
          const tok = getAccessToken("entreprise")?.trim();
          if (!tok) {
            throw new Error("Session entreprise manquante (token). Veuillez vous reconnecter.");
          }
          const nativeUrl = `${getApiBaseUrl()}${endpoint}`;
          console.warn("[ORAL REPORT] apiFetch network error, retry native fetch", { nativeUrl });
          const r2 = await fetch(nativeUrl, {
            method: "GET",
            headers: { Authorization: `Bearer ${tok}` },
          });
          if (!r2.ok) {
            const text = await r2.text().catch(() => "");
            throw new ApiError(text || `API error (HTTP ${r2.status})`, r2.status);
          }
          res = (await r2.json()) as OralReportPayload;
        } else {
          throw e;
        }
      }
      console.log("[ORAL REPORT] fetch ok", { hasTestOral: Boolean(res?.test_oral) });
      if (import.meta.env.DEV && Array.isArray(res?.questions)) {
        for (const q of res.questions) {
          console.log("[QUALITY DEBUG]", {
            question_order: q.question_order,
            pertinence: q.relevance_score,
            hesitation: q.hesitation_score,
            coherence_score: q.coherence_score ?? null,
            composite_quality_score: q.composite_quality_score ?? null,
            final_quality: q.quality_label,
          });
        }
      }
      setData(res);
    } catch (e) {
      console.error("[ORAL REPORT] fetch error", e);
      setError(e instanceof Error ? e.message : "Chargement impossible (erreur réseau).");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [candidatureId]);

  useEffect(() => {
    console.log("[ORAL REPORT DEBUG] useEffect fired", { open, candidatureId });
    if (!open || !candidatureId) return;
    void loadReport();
  }, [open, candidatureId, loadReport]);

  useEffect(() => {
    if (!open) return;
    const body = document.body;
    const html = document.documentElement;
    const prevBodyOverflow = body.style.overflow;
    const prevHtmlOverflow = html.style.overflow;
    const prevBodyPaddingRight = body.style.paddingRight;
    const prevHtmlPaddingRight = html.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    body.style.overflow = "hidden";
    html.style.overflow = "hidden";
    if (scrollbarWidth > 0) {
      const pad = `${scrollbarWidth}px`;
      body.style.paddingRight = pad;
      html.style.paddingRight = pad;
    }
    return () => {
      body.style.overflow = prevBodyOverflow;
      html.style.overflow = prevHtmlOverflow;
      body.style.paddingRight = prevBodyPaddingRight;
      html.style.paddingRight = prevHtmlPaddingRight;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  const to = data?.test_oral;
  const toral = to as Record<string, unknown> | null | undefined;
  const stressScoreNum = oralReportParseScore(toral?.stress_score);
  const confidenceScoreNum = oralReportParseScore(toral?.confidence_score);
  const stressPhrase = `Stress : ${stressDisplayLabel(stressScoreNum)}`;
  const confidencePhrase = `Confiance : ${confidenceDisplayLabel(confidenceScoreNum)}`;

  if (!open) return null;

  return createPortal(
    <div className="pointer-events-auto fixed inset-0 z-[200] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
        aria-hidden
        onClick={(e) => {
          if (e.target === e.currentTarget) onOpenChange(false);
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="pointer-events-auto relative z-[201] flex w-full max-w-3xl flex-col overflow-hidden rounded-2xl border bg-background shadow-2xl"
        style={{ maxHeight: "min(85vh, calc(100dvh - 2rem))" }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex shrink-0 items-start justify-between gap-3 border-b bg-background px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Rapport d&apos;entretien oral</h2>
            <p className="text-sm text-muted-foreground">{candidateLabel}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            aria-label="Fermer"
            className="relative z-20 shrink-0"
          >
            <X className="h-5 w-5" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          {loading ? (
            <div className="flex items-center gap-2 py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              Chargement du rapport…
            </div>
          ) : null}
          {error ? (
            <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}

          {!loading && data && !to ? (
            <p className="text-sm text-muted-foreground">Aucun entretien oral enregistré pour ce candidat.</p>
          ) : null}

          {!loading && data && to ? (
            <div className="space-y-8 pb-8">
              <section className="flex justify-center">
                {resolveApiAssetUrl(
                  data.candidate_photo_url || data.candidate_image_url || data.primary_snapshot_url,
                ) ? (
                  <img
                    src={
                      resolveApiAssetUrl(
                        data.candidate_photo_url || data.candidate_image_url || data.primary_snapshot_url,
                      ) ?? ""
                    }
                    alt="Candidat"
                    className="h-24 w-24 rounded-full border object-cover shadow"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-24 w-24 items-center justify-center rounded-full border bg-muted text-lg font-semibold text-muted-foreground shadow">
                    {initialsFromLabel(candidateLabel)}
                  </div>
                )}
              </section>

              {data.badge?.badge_display ? (
                <section className="rounded-xl border bg-card p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Synthèse automatique
                  </p>
                  <Badge className="mt-2 text-sm" variant="secondary">
                    {data.badge.badge_display}
                  </Badge>
                  {data.ai_summary ? (
                    <p className="mt-3 text-sm leading-relaxed text-foreground/90">{data.ai_summary}</p>
                  ) : null}
                </section>
              ) : null}

              {data.ai_report?.strengths?.length ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Points forts</h3>
                  <ul className="list-inside list-disc space-y-1 text-sm text-foreground/90">
                    {data.ai_report.strengths.map((s, i) => (
                      <li key={`s-${i}`}>{s}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {data.ai_report?.weaknesses?.length ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Points à améliorer</h3>
                  <ul className="list-inside list-disc space-y-1 text-sm text-foreground/90">
                    {data.ai_report.weaknesses.map((s, i) => (
                      <li key={`w-${i}`}>{s}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section className="rounded-xl border bg-card p-4">
                <h3 className="mb-3 text-sm font-semibold">Indicateurs globaux</h3>
                <dl className="grid gap-2 text-sm sm:grid-cols-2">
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-muted-foreground">Score oral (contenu)</dt>
                    <dd className="font-medium tabular-nums">{String(to.score_oral_global ?? "—")}</dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-muted-foreground">Confiance (estim.)</dt>
                    <dd className="font-medium">
                      {confidencePhrase}
                      {ENABLE_ADVANCED_METRICS && confidenceScoreNum != null
                        ? ` (${confidenceScoreNum})`
                        : ""}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-muted-foreground">Stress (estim.)</dt>
                    <dd className="font-medium">
                      {stressPhrase}
                      {ENABLE_ADVANCED_METRICS && stressScoreNum != null ? ` (${stressScoreNum})` : ""}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2 sm:col-span-2">
                    <dt className="text-muted-foreground">Niveau linguistique (si disponible)</dt>
                    <dd className="font-medium">{String(to.language_display ?? "—")}</dd>
                  </div>
                </dl>
              </section>

              <section className="rounded-xl border bg-card p-4">
                <h3 className="mb-2 text-sm font-semibold">Proctoring (indicateurs)</h3>
                <p className="mb-3 text-sm font-medium text-foreground">{String(to.proctoring_summary_label ?? "—")}</p>
                <ul className="grid gap-1 text-sm text-muted-foreground sm:grid-cols-2">
                  <li>Onglets : {String(to.tab_switch_count ?? 0)}</li>
                  <li>Anomalie de présence : {to.presence_anomaly_detected ? "oui" : "non"}</li>
                  <li>
                    Signal téléphone : {phoneSignalPhrase(toral?.phone_detected)}
                  </li>
                  <li>Autre personne : {to.other_person_detected ? "oui" : "non"}</li>
                  <li>
                    Regard dominant :{" "}
                    {String(data.proctoring_insights?.dominant_direction ?? "—")}
                  </li>
                  <li>
                    Mouvement tête :{" "}
                    {String(data.proctoring_insights?.head_movement ?? "—")}
                  </li>
                  <li className="sm:col-span-2">
                    Suspicion :{" "}
                    {String(data.proctoring_insights?.suspicion_level ?? "—")}
                    {data.proctoring_insights?.suspicion_score != null
                      ? ` (${String(data.proctoring_insights.suspicion_score)}/100)`
                      : ""}
                  </li>
                </ul>
              </section>

              {data.proctoring_insights || data.behavioral_analysis ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Analyse comportementale</h3>
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {data.proctoring_insights?.gaze_professional ? (
                      <li>- {data.proctoring_insights.gaze_professional}</li>
                    ) : null}
                    {data.proctoring_insights?.movement_professional ? (
                      <li>- {data.proctoring_insights.movement_professional}</li>
                    ) : null}
                    {data.proctoring_insights?.presence_professional ? (
                      <li>- {data.proctoring_insights.presence_professional}</li>
                    ) : null}
                    {data.proctoring_insights?.suspicion_professional ? (
                      <li>- {data.proctoring_insights.suspicion_professional}</li>
                    ) : null}
                    {data.behavioral_analysis?.visual && !data.proctoring_insights?.gaze_professional ? (
                      <li>- {data.behavioral_analysis.visual}</li>
                    ) : null}
                    {data.behavioral_analysis?.suspicion && !data.proctoring_insights?.suspicion_professional ? (
                      <li>- {data.behavioral_analysis.suspicion}</li>
                    ) : null}
                  </ul>
                </section>
              ) : null}

              {data.ai_report &&
              (data.ai_report.recommendation ||
                data.ai_report.risk_notes ||
                data.ai_report.decision_reason ||
                data.ai_report.conclusion) ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Synthèse intelligente (deep AI)</h3>
                  {data.ai_report.recommendation ? (
                    <p className="mt-1 text-sm text-foreground/90">
                      <span className="font-medium">Recommandation RH :</span> {data.ai_report.recommendation}
                    </p>
                  ) : null}
                  {data.ai_report.risk_notes ? (
                    <p className="mt-2 text-sm text-foreground/90">
                      <span className="font-medium">Risques / vigilance :</span> {data.ai_report.risk_notes}
                    </p>
                  ) : null}
                  {data.ai_report.decision_reason ? (
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                      <span className="font-medium text-foreground/80">Motif (données) :</span>{" "}
                      {data.ai_report.decision_reason}
                    </p>
                  ) : null}
                  {data.ai_report.conclusion ? (
                    <p className="mt-3 text-sm font-medium text-foreground">
                      Conclusion : {data.ai_report.conclusion}
                    </p>
                  ) : null}
                </section>
              ) : null}

              <section>
                <h3 className="mb-2 text-sm font-semibold">Questions &amp; réponses</h3>
                <div className="space-y-4">
                  {data.questions.map((q) => {
                    const tone = qualityTone(q.quality_label);
                    return (
                      <div key={q.question_order} className="rounded-xl border bg-card p-4">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <Badge variant="outline">Q{q.question_order}</Badge>
                          <Badge className={qualityClass(tone)}>Qualité : {q.quality_label}</Badge>
                          <span className="text-xs text-muted-foreground tabular-nums">
                            Pertinence {q.relevance_score ?? "—"} · Hésitation {q.hesitation_score ?? "—"}
                          </span>
                        </div>
                        <p className="text-sm font-medium text-foreground">{q.question_text}</p>
                        <p className="mt-2 text-sm text-muted-foreground whitespace-pre-wrap">
                          {q.transcript_text || "—"}
                        </p>
                        {q.audio_url ? (
                          <div className="mt-3">
                            <p className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                              <Mic className="h-3.5 w-3.5" />
                              Audio ({q.answer_duration_seconds != null ? `${q.answer_duration_seconds}s` : "durée N/A"})
                            </p>
                            <audio
                              controls
                              className="h-9 w-full max-w-md"
                              src={resolveApiAssetUrl(q.audio_url) ?? undefined}
                            />
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </section>

              {data.timeline?.length ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Chronologie des signaux</h3>
                  <ul className="space-y-1.5 text-sm">
                    {data.timeline.map((ev, i) => (
                      <li key={`${ev.time_display}-${i}`} className="flex gap-2">
                        <span className="w-14 shrink-0 font-mono text-xs text-muted-foreground">
                          {ev.time_display}
                        </span>
                        <span>{ev.label_fr}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          ) : null}
        </div>

        <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t bg-background px-5 py-3">
          <Button
            type="button"
            variant="default"
            size="sm"
            className="gap-2"
            disabled={pdfLoading || !to}
            onClick={async () => {
              setPdfLoading(true);
              try {
                await downloadPdf(candidatureId);
              } catch (e) {
                alert(e instanceof Error ? e.message : "Échec du téléchargement PDF.");
              } finally {
                setPdfLoading(false);
              }
            }}
          >
            {pdfLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
            Télécharger le rapport complet (PDF)
          </Button>
        </footer>
      </div>
    </div>,
    portalContainer ?? document.body,
  );
};

export default OralReportDialog;
