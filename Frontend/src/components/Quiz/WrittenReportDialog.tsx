import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/services/authService";

type Summary = {
  correct_count: number | null;
  incorrect_count: number | null;
  partial_count: number | null;
  success_rate_percent: number | null;
  final_message: string;
} | null;

type QuestionRow = {
  order: number;
  question_text: string | null;
  options: string[];
  expected_answer: unknown;
  candidate_answer: unknown;
  /** Libellé optionnel renvoyé par l’API (texte lisible + lettre). */
  correct_answer_display?: string | null;
  candidate_answer_display?: string | null;
  status: string;
  score_label?: string | null;
};

type ExerciceBlock = {
  title?: string | null;
  consigne?: string | null;
  candidate_submission?: string | null;
  evaluation_score?: number | null;
  feedback?: string | null;
} | null;

type WrittenReportPayload = {
  candidature_id: string;
  offre_titre: string | null;
  epreuve_type: string;
  test_present: boolean;
  score_ecrit: number | null;
  status_reussite: boolean | null;
  detail_available: boolean;
  detail_missing_hint: string | null;
  questions: QuestionRow[];
  exercice: ExerciceBlock;
  summary: Summary;
};

function statusTone(status: string): "good" | "mid" | "bad" {
  const s = status.toLowerCase();
  if (s === "correct") return "good";
  if (s === "partial") return "mid";
  return "bad";
}

function statusBadgeClass(tone: "good" | "mid" | "bad"): string {
  if (tone === "good") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-900 dark:text-emerald-100";
  if (tone === "mid") return "border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-100";
  return "border-red-500/40 bg-red-500/10 text-red-900 dark:text-red-100";
}

function statusLabelFr(status: string): string {
  const s = status.toLowerCase();
  if (s === "correct") return "Correcte";
  if (s === "partial") return "Partielle";
  return "Incorrecte";
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidatureId: string;
  candidateLabel: string;
  /** Si fourni (ex. nœud dans le Sheet candidat), le portail s’y attache pour rester dans l’arbre du Dialog Radix. */
  portalContainer?: HTMLElement | null;
};

const WrittenReportDialog = ({
  open,
  onOpenChange,
  candidatureId,
  candidateLabel,
  portalContainer,
}: Props) => {
  const [data, setData] = useState<WrittenReportPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = (await apiFetch(
        `/api/quiz/results/${encodeURIComponent(candidatureId)}`,
      )) as WrittenReportPayload;
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chargement impossible.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [candidatureId]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

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

  const reussiteBadge =
    data?.status_reussite === true
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-900 dark:text-emerald-100"
      : data?.status_reussite === false
        ? "border-red-500/40 bg-red-500/10 text-red-900 dark:text-red-100"
        : "border-muted bg-muted/40 text-muted-foreground";

  if (!open) return null;

  return createPortal(
    <div className="pointer-events-auto fixed inset-0 z-[200] flex items-center justify-center overflow-hidden p-4">
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
        <header className="sticky top-0 z-30 flex shrink-0 items-start justify-between gap-3 border-b bg-background px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Rapport du test écrit</h2>
            <p className="text-sm text-muted-foreground">{candidateLabel}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            aria-label="Fermer"
            className="relative z-40 shrink-0"
          >
            <X className="h-5 w-5" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 touch-pan-y overflow-y-auto overscroll-contain px-5 py-4">
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

          {!loading && data && !data.test_present ? (
            <p className="text-sm text-muted-foreground">Aucun test écrit enregistré pour cette candidature.</p>
          ) : null}

          {!loading && data && data.test_present ? (
            <div className="space-y-8 pb-8">
              <section className="rounded-xl border bg-card p-4">
                <h3 className="mb-3 text-sm font-semibold">Informations globales</h3>
                <dl className="grid gap-2 text-sm sm:grid-cols-2">
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2 sm:col-span-2">
                    <dt className="text-muted-foreground">Score test écrit</dt>
                    <dd className="font-semibold tabular-nums">
                      {data.score_ecrit != null ? `${Math.round(data.score_ecrit)} %` : "—"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2 sm:col-span-2">
                    <dt className="text-muted-foreground">Résultat</dt>
                    <dd>
                      <Badge className={reussiteBadge} variant="outline">
                        {data.status_reussite ? "Réussi" : "Non réussi"}
                      </Badge>
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-muted-foreground">Épreuve</dt>
                    <dd className="font-medium text-right">{data.epreuve_type}</dd>
                  </div>
                  <div className="flex justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2 sm:col-span-2">
                    <dt className="text-muted-foreground">Offre</dt>
                    <dd className="text-right font-medium">{data.offre_titre ?? "—"}</dd>
                  </div>
                </dl>
              </section>

              {data.detail_missing_hint ? (
                <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-950 dark:text-amber-100">
                  {data.detail_missing_hint}
                </p>
              ) : null}

              {data.exercice ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-3 text-sm font-semibold">Exercice</h3>
                  <p className="text-sm font-medium text-foreground">{data.exercice.title ?? "Exercice"}</p>
                  <div className="mt-3 space-y-2 text-sm">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Consigne</p>
                    <p className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-foreground/90">
                      {data.exercice.consigne ?? "—"}
                    </p>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Réponse soumise</p>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border bg-background p-3 text-xs">
                      {String(data.exercice.candidate_submission ?? "—")}
                    </pre>
                    {data.exercice.feedback ? (
                      <>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Évaluation (aperçu)
                        </p>
                        <p className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-foreground/90">
                          {data.exercice.feedback}
                        </p>
                      </>
                    ) : null}
                  </div>
                </section>
              ) : null}

              {data.questions.length > 0 ? (
                <section>
                  <h3 className="mb-3 text-sm font-semibold">Questions &amp; réponses</h3>
                  <div className="space-y-4">
                    {data.questions.map((q) => {
                      const tone = statusTone(q.status);
                      return (
                        <div key={q.order} className="rounded-xl border bg-card p-4 shadow-sm">
                          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs font-medium text-muted-foreground">Question {q.order + 1}</span>
                            <Badge className={statusBadgeClass(tone)} variant="outline">
                              {statusLabelFr(q.status)}
                            </Badge>
                          </div>
                          <p className="text-sm font-medium text-foreground">{q.question_text ?? "—"}</p>
                          {q.options?.length ? (
                            <ul className="mt-2 list-inside list-disc text-sm text-muted-foreground">
                              {q.options.map((opt, i) => (
                                <li key={i}>{opt}</li>
                              ))}
                            </ul>
                          ) : null}
                          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                            <div>
                              <dt className="text-muted-foreground">Réponse du candidat</dt>
                              <dd className="font-medium">
                                {String(q.candidate_answer_display ?? q.candidate_answer ?? "—")}
                              </dd>
                            </div>
                            <div>
                              <dt className="text-muted-foreground">Bonne réponse</dt>
                              <dd className="font-medium">
                                {String(q.correct_answer_display ?? q.expected_answer ?? "—")}
                              </dd>
                            </div>
                            {q.score_label ? (
                              <div className="sm:col-span-2">
                                <dt className="text-muted-foreground">Indicateur</dt>
                                <dd className="font-medium">{q.score_label}</dd>
                              </div>
                            ) : null}
                          </dl>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ) : null}

              {data.summary ? (
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-3 text-sm font-semibold">Synthèse</h3>
                  <ul className="space-y-2 text-sm">
                    <li className="flex justify-between gap-4 rounded-lg bg-muted/40 px-3 py-2">
                      <span className="text-muted-foreground">Bonnes réponses</span>
                      <span className="font-medium tabular-nums">{data.summary.correct_count ?? "—"}</span>
                    </li>
                    <li className="flex justify-between gap-4 rounded-lg bg-muted/40 px-3 py-2">
                      <span className="text-muted-foreground">Mauvaises réponses</span>
                      <span className="font-medium tabular-nums">{data.summary.incorrect_count ?? "—"}</span>
                    </li>
                    <li className="flex justify-between gap-4 rounded-lg bg-muted/40 px-3 py-2">
                      <span className="text-muted-foreground">Réponses partielles</span>
                      <span className="font-medium tabular-nums">{data.summary.partial_count ?? "—"}</span>
                    </li>
                    <li className="flex justify-between gap-4 rounded-lg bg-muted/40 px-3 py-2">
                      <span className="text-muted-foreground">Taux affiché</span>
                      <span className="font-medium tabular-nums">
                        {data.summary.success_rate_percent != null
                          ? `${data.summary.success_rate_percent} %`
                          : "—"}
                      </span>
                    </li>
                    <li className="flex justify-between gap-4 rounded-lg border px-3 py-2">
                      <span className="font-medium">Verdict</span>
                      <span className="font-semibold">{data.summary.final_message}</span>
                    </li>
                  </ul>
                </section>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>,
    portalContainer ?? document.body,
  );
};

export default WrittenReportDialog;
