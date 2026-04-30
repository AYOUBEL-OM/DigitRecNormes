import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, Mail, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { sendCandidateEmail, type CandidatureDetailsResponse } from "@/services/authService";

function companyNameFromStorage(): string {
  try {
    const raw = localStorage.getItem("entreprise_user");
    if (!raw?.trim()) return "Notre équipe de recrutement";
    const u = JSON.parse(raw) as { type?: string; nom?: string };
    if (u.type === "entreprise" && u.nom?.trim()) return u.nom.trim();
  } catch {
    /* ignore */
  }
  return "Notre équipe de recrutement";
}

function defaultSubject(offreTitre: string | null): string {
  const t = (offreTitre ?? "").trim() || "votre candidature";
  return `Suite à votre candidature – ${t}`;
}

function defaultMessage(
  prenom: string,
  nom: string,
  offreTitre: string | null,
  company: string,
): string {
  const p = prenom.trim();
  const n = nom.trim();
  const greet =
    p || n
      ? `Bonjour${p ? ` ${p}` : ""}${n ? ` ${n}` : ""},`
      : "Bonjour,";
  const poste = (offreTitre ?? "").trim() || "notre offre";
  return (
    `${greet}\n\n` +
    `Nous vous contactons concernant votre candidature pour le poste : ${poste}.\n\n` +
    `Nous reviendrons vers vous prochainement concernant la suite du processus.\n\n` +
    `Cordialement,\n` +
    `${company}`
  );
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidatureId: string;
  details: CandidatureDetailsResponse;
  /** Si fourni (ex. nœud dans le Sheet candidat), le portail s’y attache pour rester dans l’arbre du Dialog Radix. */
  portalContainer?: HTMLElement | null;
};

const CandidateEmailDialog = ({
  open,
  onOpenChange,
  candidatureId,
  details,
  portalContainer,
}: Props) => {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const resetFromDetails = useCallback(() => {
    const company = companyNameFromStorage();
    setTo(details.candidate.email?.trim() ?? "");
    setSubject(defaultSubject(details.offre_titre));
    setMessage(
      defaultMessage(
        details.candidate.prenom ?? "",
        details.candidate.nom ?? "",
        details.offre_titre,
        company,
      ),
    );
    setFeedback(null);
  }, [details]);

  useEffect(() => {
    if (open) resetFromDetails();
  }, [open, resetFromDetails]);

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

  const handleSend = async () => {
    setFeedback(null);
    const toTrim = to.trim();
    const subTrim = subject.trim();
    const msgTrim = message.trim();
    if (!toTrim || !subTrim || !msgTrim) {
      setFeedback({ type: "err", text: "Veuillez remplir le destinataire, le sujet et le message." });
      return;
    }
    setSending(true);
    try {
      await sendCandidateEmail({
        candidature_id: candidatureId,
        to: toTrim,
        subject: subTrim,
        message: msgTrim,
      });
      setFeedback({ type: "ok", text: "Email envoyé avec succès." });
    } catch (e) {
      setFeedback({
        type: "err",
        text: e instanceof Error ? e.message : "Envoi impossible.",
      });
    } finally {
      setSending(false);
    }
  };

  if (!open) return null;

  const root = (
    <div className="pointer-events-auto fixed inset-0 z-[200] flex items-center justify-center overflow-hidden p-4">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px]"
        aria-hidden
        onClick={(e) => {
          if (e.target === e.currentTarget && !sending) onOpenChange(false);
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="candidate-email-title"
        className="pointer-events-auto relative z-[201] flex max-h-[min(90vh,calc(100dvh-2rem))] w-full max-w-lg flex-col overflow-hidden rounded-xl border bg-background shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
      >
        <header className="sticky top-0 z-30 flex shrink-0 items-start justify-between gap-3 border-b bg-background px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="mt-0.5 shrink-0 rounded-lg bg-primary/10 p-2 text-primary">
              <Mail className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 id="candidate-email-title" className="text-lg font-semibold tracking-tight">
                Envoyer un email
              </h2>
              <p className="text-sm text-muted-foreground">
                Vous pouvez modifier le sujet et le message avant l’envoi.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={sending}
            onClick={() => onOpenChange(false)}
            aria-label="Fermer"
            className="relative z-40 shrink-0"
          >
            <X className="h-5 w-5" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 touch-pan-y space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
          <div className="space-y-2">
            <Label htmlFor="cand-email-to">Destinataire</Label>
            <Input
              id="cand-email-to"
              type="email"
              autoComplete="email"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              disabled={sending}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">
              L’envoi n’est autorisé que vers l’email du candidat enregistré sur cette candidature.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="cand-email-subject">Objet</Label>
            <Input
              id="cand-email-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              disabled={sending}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cand-email-body">Message</Label>
            <Textarea
              id="cand-email-body"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={sending}
              rows={12}
              className="min-h-[200px] resize-y text-sm leading-relaxed"
            />
          </div>
          {feedback ? (
            <p
              className={
                feedback.type === "ok"
                  ? "rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-900 dark:text-emerald-100"
                  : "rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              }
              role="status"
            >
              {feedback.text}
            </p>
          ) : null}
        </div>

        <footer className="relative z-30 flex shrink-0 flex-wrap justify-end gap-2 border-t bg-muted/20 px-5 py-4">
          <Button type="button" variant="outline" disabled={sending} onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button type="button" disabled={sending} onClick={() => void handleSend()}>
            {sending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Envoi…
              </>
            ) : (
              "Envoyer"
            )}
          </Button>
        </footer>
      </div>
    </div>
  );

  return createPortal(root, portalContainer ?? document.body);
};

export default CandidateEmailDialog;
