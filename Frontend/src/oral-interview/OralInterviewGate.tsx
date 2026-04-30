import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import OralCandidateLogin from "@/oral-interview/OralCandidateLogin";
import { fetchOralBootstrap } from "@/oral-interview/services/oralOfferService";
import {
  ApiError,
  clearAuthStorage,
  clearPendingOralTokenFromSession,
  getAccessToken,
  getPendingOralTokenFromSession,
  setOralInterviewAccessToken,
  setPendingOralTokenInSession,
} from "@/services/authService";

type GatePhase = "checking" | "login" | "error";

/**
 * Point d’entrée des liens e-mail : exige un JWT candidat + jeton oral valides avant
 * `/interview/start`.
 */
const OralInterviewGate = () => {
  const navigate = useNavigate();
  const params = useParams();
  const [searchParams] = useSearchParams();
  const [phase, setPhase] = useState<GatePhase>("checking");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  const pathToken = params.token?.trim() || "";
  const queryToken = searchParams.get("oral_token")?.trim() || "";

  useEffect(() => {
    let alive = true;

    const run = async () => {
      setPhase("checking");
      setErrorMessage(null);

      const raw = pathToken || queryToken;
      let oralToken = getPendingOralTokenFromSession() || "";

      if (raw) {
        try {
          const decoded = decodeURIComponent(raw);
          if (decoded) {
            setPendingOralTokenInSession(decoded);
            oralToken = decoded;
          }
        } catch {
          if (!alive) return;
          setPhase("error");
          setErrorMessage("Lien d’invitation invalide.");
          return;
        }
      }

      if (!oralToken.trim()) {
        if (!alive) return;
        setPhase("error");
        setErrorMessage(
          "Lien d’invitation incomplet. Ouvrez l’URL reçue par e-mail après votre test écrit.",
        );
        return;
      }

      const jwt = getAccessToken("candidat")?.trim();
      if (!jwt) {
        if (!alive) return;
        setPhase("login");
        return;
      }

      try {
        await fetchOralBootstrap({ oralTokenOverride: oralToken });
        if (!alive) return;
        setOralInterviewAccessToken(oralToken);
        clearPendingOralTokenFromSession();
        navigate("/interview/start", { replace: true });
      } catch (e) {
        if (!alive) return;
        const msg =
          e instanceof ApiError
            ? e.message
            : e instanceof Error
              ? e.message
              : "Accès refusé.";
        if (e instanceof ApiError && e.status === 401) {
          setPhase("login");
          setErrorMessage("Votre session a expiré. Reconnectez-vous pour continuer.");
          return;
        }
        setPhase("error");
        setErrorMessage(msg);
      }
    };

    void run();
    return () => {
      alive = false;
    };
  }, [pathToken, queryToken, navigate, retryNonce]);

  const handleLoginSessionReady = async () => {
    const oralToken =
      getPendingOralTokenFromSession()?.trim() ||
      (() => {
        const raw = pathToken || queryToken;
        if (!raw) return "";
        try {
          const decoded = decodeURIComponent(raw);
          if (decoded) setPendingOralTokenInSession(decoded);
          return decoded || "";
        } catch {
          return "";
        }
      })();

    if (!oralToken) {
      setErrorMessage("Jeton d’entretien perdu. Rouvrez le lien reçu par e-mail.");
      throw new Error("Jeton d’entretien manquant.");
    }

    await fetchOralBootstrap({ oralTokenOverride: oralToken });
    setOralInterviewAccessToken(oralToken);
    clearPendingOralTokenFromSession();
    navigate("/interview/start", { replace: true });
  };

  if (phase === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-primary/5 px-4">
        <div className="flex flex-col items-center gap-4">
          <div className="h-14 w-14 animate-pulse rounded-xl border border-primary/20 bg-primary/5 card-shadow" />
          <p className="text-sm font-medium text-muted-foreground">Vérification de l&apos;accès…</p>
        </div>
      </div>
    );
  }

  if (phase === "login") {
    return (
      <div>
        {errorMessage ? (
          <div
            className="mx-auto max-w-md px-4 pt-6 text-center text-sm text-amber-800 dark:text-amber-100"
            role="status"
          >
            {errorMessage}
          </div>
        ) : null}
        <OralCandidateLogin onSessionReady={handleLoginSessionReady} />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-background to-primary/5 p-6 text-center">
      <div className="w-full max-w-lg rounded-xl border border-destructive/25 bg-card p-8 shadow-lg">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertCircle className="h-7 w-7" aria-hidden />
        </div>
        <h1 className="text-xl font-semibold text-primary">Accès non autorisé</h1>
        <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
          {errorMessage || "Impossible d’accéder à cet entretien."}
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              clearAuthStorage("candidat");
              setRetryNonce((n) => n + 1);
            }}
          >
            Changer de compte candidat
          </Button>
          <Button
            type="button"
            onClick={() => {
              const raw = pathToken || queryToken;
              if (raw) {
                try {
                  const decoded = decodeURIComponent(raw);
                  if (decoded) setPendingOralTokenInSession(decoded);
                } catch {
                  /* ignore */
                }
              }
              setRetryNonce((n) => n + 1);
            }}
          >
            Réessayer
          </Button>
        </div>
      </div>
    </div>
  );
};

export default OralInterviewGate;
