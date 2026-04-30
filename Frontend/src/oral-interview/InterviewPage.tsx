import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Camera, CheckCircle2, Mic, Video, X, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  apiFetch,
  getAccessToken,
  getApiBaseUrl,
  getOralInterviewAccessToken,
  ORAL_SESSION_HEADER,
  setOralInterviewAccessToken,
} from "@/services/authService";
import { cn } from "@/lib/utils";
import CameraPreview from "@/oral-interview/components/CameraPreview";
import OralInterviewTimer from "@/oral-interview/components/OralInterviewTimer";
import {
  ORAL_ANSWER_TIME_DEFAULT,
  ORAL_PREP_TIME,
  getAnswerSecondsForQuestion,
} from "@/oral-interview/constants/oralTiming";
import { useRecorder } from "@/oral-interview/hooks/useRecorder";
import { TAB_VISIBILITY_MESSAGE, useOralProctoring } from "@/oral-interview/hooks/useOralProctoring";
import { fetchOralBootstrap, type OralOffreSummary } from "@/oral-interview/services/oralOfferService";

/**
 * Page d’entretien oral (route `/interview/start` ou `/interview/:token/start`) :
 * JWT candidat + jeton oral requis ; le gate d’accès alimente le stockage avant l’arrivée ici.
 */
const InterviewPage = () => {
  const navigate = useNavigate();
  const params = useParams();

  const [sessionToken, setSessionToken] = useState<string | undefined>(
    () => getOralInterviewAccessToken() ?? undefined,
  );

  /** Normalise `/interview/:token/start` → stocke le jeton puis `/interview/start`. */
  useEffect(() => {
    const fromPath = params.token?.trim();
    if (!fromPath) return;
    let decoded: string;
    try {
      decoded = decodeURIComponent(fromPath);
    } catch {
      navigate("/interview", { replace: true });
      return;
    }
    if (!decoded) {
      navigate("/interview", { replace: true });
      return;
    }
    setOralInterviewAccessToken(decoded);
    setSessionToken(decoded);
    navigate("/interview/start", { replace: true });
  }, [params.token, navigate]);

  /** Sans session complète, retour au point d’entrée (lien e-mail). */
  useEffect(() => {
    if (params.token?.trim()) return;
    const jwt = getAccessToken("candidat")?.trim();
    const oral = getOralInterviewAccessToken()?.trim();
    if (jwt?.trim() && oral?.trim()) return;
    if (oral?.trim() && !jwt?.trim()) {
      navigate(`/interview?oral_token=${encodeURIComponent(oral)}`, { replace: true });
      return;
    }
    navigate("/interview", { replace: true });
  }, [params.token, navigate]);

  useEffect(() => {
    const sync = () => setSessionToken(getOralInterviewAccessToken() ?? undefined);
    window.addEventListener("digitrec:oral-session-update", sync);
    return () => window.removeEventListener("digitrec:oral-session-update", sync);
  }, []);

  const token = sessionToken;

  const shellRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const identityVideoRef = useRef<HTMLVideoElement>(null);

  const [identityPhotoConfirmed, setIdentityPhotoConfirmed] = useState(false);
  const [identityPhase, setIdentityPhase] = useState<"live" | "preview">("live");
  const [identityCameraReady, setIdentityCameraReady] = useState(false);
  const [capturedIdentityDataUrl, setCapturedIdentityDataUrl] = useState<string | null>(null);
  const [identityUploading, setIdentityUploading] = useState(false);

  const [offer, setOffer] = useState<OralOffreSummary | null>(null);
  const [questions, setQuestions] = useState<string[]>([]);
  const [genError, setGenError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFinished, setIsFinished] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isFinalizingAnalysis, setIsFinalizingAnalysis] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [micReady, setMicReady] = useState(false);
  const [mediaCheckNonce, setMediaCheckNonce] = useState(0);

  const lastProcessedBlob = useRef<Blob | null>(null);
  const finalizeTriggeredRef = useRef(false);
  const finalizeControllerRef = useRef<AbortController | null>(null);
  const prepConsumedRef = useRef(false);
  const needsPrepBootstrapRef = useRef(false);
  const prevRecordingRef = useRef(false);
  const [prepSecondsLeft, setPrepSecondsLeft] = useState<number | null>(null);
  const [answerSecondsLeft, setAnswerSecondsLeft] = useState<number | null>(null);

  const {
    isRecording,
    startRecording,
    stopRecording,
    audioBlob,
    lastDurationSeconds,
    clearRecordingOutput,
  } = useRecorder();

  const mediaReady = cameraReady && micReady;
  /** Proctoring actif dès que les questions sont prêtes, jusqu’à la fin (pas seulement pendant l’enregistrement). */
  const proctoringEnabled =
    Boolean(token?.trim()) && !loading && questions.length > 0 && !genError && !isFinished;

  const getProctoringVideoElement = useCallback(() => {
    if (questions.length > 0 && !genError && !identityPhotoConfirmed) {
      return identityVideoRef.current;
    }
    return videoRef.current;
  }, [questions.length, genError, identityPhotoConfirmed]);

  const { warnings, dismissWarning, endSession } = useOralProctoring({
    accessToken: token,
    videoRef,
    getVideoElement: getProctoringVideoElement,
    enabled: proctoringEnabled,
  });

  /** Onglet : bannière fixe. Téléphone : pas d’alerte intrusive (détection toujours active côté API / rapport). */
  const warningsWithoutTab = useMemo(
    () =>
      warnings.filter(
        (w) =>
          w.id !== "tab" &&
          w.id !== "phone" &&
          w.id !== "phone_hb" &&
          !String(w.id).startsWith("phone_"),
      ),
    [warnings],
  );

  const allowedAnswerSeconds = useMemo(
    () =>
      questions.length > 0
        ? getAnswerSecondsForQuestion(questions[currentIndex] ?? "", currentIndex)
        : ORAL_ANSWER_TIME_DEFAULT,
    [questions, currentIndex],
  );

  const timerPhase = useMemo(() => {
    if (prepSecondsLeft != null && prepSecondsLeft > 0) return "prep" as const;
    if (isRecording) return "answer" as const;
    return "idle" as const;
  }, [prepSecondsLeft, isRecording]);

  /** Changement de question : arrêt propre, blob effacé ; le compte à rebours de préparation est réinjecté une fois le média prêt. */
  useEffect(() => {
    if (questions.length === 0 || genError) return;
    stopRecording();
    clearRecordingOutput();
    prepConsumedRef.current = false;
    setAnswerSecondsLeft(null);
    setPrepSecondsLeft(null);
    needsPrepBootstrapRef.current = true;
  }, [currentIndex, questions.length, genError, stopRecording, clearRecordingOutput]);

  useEffect(() => {
    if (!mediaReady || questions.length === 0 || genError) return;
    if (!needsPrepBootstrapRef.current) return;
    needsPrepBootstrapRef.current = false;
    setPrepSecondsLeft(ORAL_PREP_TIME);
    prepConsumedRef.current = false;
  }, [mediaReady, questions.length, genError, currentIndex]);

  const inPrepCountdown = prepSecondsLeft != null && prepSecondsLeft > 0 && mediaReady;

  useEffect(() => {
    if (!inPrepCountdown) return;
    const id = window.setInterval(() => {
      setPrepSecondsLeft((s) => {
        if (s == null || s <= 1) return 0;
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [inPrepCountdown, currentIndex]);

  useEffect(() => {
    if (prepSecondsLeft !== 0 || !mediaReady || questions.length === 0 || genError) return;
    if (prepConsumedRef.current) return;
    prepConsumedRef.current = true;
    setPrepSecondsLeft(null);
    const allowed = getAnswerSecondsForQuestion(questions[currentIndex], currentIndex);
    setAnswerSecondsLeft(allowed);
    void (async () => {
      try {
        await startRecording();
      } catch (e) {
        console.error(e);
        prepConsumedRef.current = false;
        setPrepSecondsLeft(ORAL_PREP_TIME);
        setAnswerSecondsLeft(null);
      }
    })();
  }, [
    prepSecondsLeft,
    mediaReady,
    questions,
    currentIndex,
    genError,
    startRecording,
  ]);

  const inAnswerCountdown =
    isRecording && answerSecondsLeft != null && answerSecondsLeft > 0;

  useEffect(() => {
    if (!inAnswerCountdown) return;
    const id = window.setInterval(() => {
      setAnswerSecondsLeft((s) => {
        if (s == null || s <= 1) return 0;
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [inAnswerCountdown, currentIndex]);

  useEffect(() => {
    if (!isRecording || answerSecondsLeft !== 0) return;
    stopRecording();
  }, [isRecording, answerSecondsLeft, stopRecording]);

  useEffect(() => {
    if (prevRecordingRef.current && !isRecording) {
      setAnswerSecondsLeft(null);
    }
    prevRecordingRef.current = isRecording;
  }, [isRecording]);

  useEffect(() => {
    if (isFinished) {
      endSession();
    }
  }, [isFinished, endSession]);

  /** Analyse IA différée (transcription + agrégat) : ne bloque pas le passage entre questions. */
  const finalizeAnalysisNow = useCallback(async (): Promise<boolean> => {
    if (finalizeTriggeredRef.current) {
      console.log("[ORAL DEBUG] finalize-analysis SKIPPED (finalizeTriggeredRef already true)");
      return true;
    }
    finalizeTriggeredRef.current = true;
    setIsFinalizingAnalysis(true);

    const oralToken = getOralInterviewAccessToken()?.trim() ?? "";
    const jwtCandidat = getAccessToken("candidat")?.trim() ?? "";
    const fd = new FormData();
    if (oralToken) {
      fd.append("access_token", oralToken);
    }

    console.log("[ORAL DEBUG] finalize-analysis CALL START", {
      hasOralToken: Boolean(oralToken),
      hasJwtCandidat: Boolean(jwtCandidat),
      headerOralWouldBe: oralToken ? `${ORAL_SESSION_HEADER} présent (via apiFetch)` : "absent",
      currentIndex,
      totalQuestions: questions.length,
      timeoutMs: 120000,
    });
    console.log("[oral] Finalizing analysis...");
    const controller = new AbortController();
    finalizeControllerRef.current = controller;
    const timeoutMs = 120000;
    const t = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const res = await apiFetch("/api/oral/finalize-analysis", {
        method: "POST",
        body: fd,
        signal: controller.signal,
      });
      console.log("[ORAL DEBUG] finalize-analysis RESPONSE", res);
      console.log("[oral] Finalize success", res);
      return true;
    } catch (err) {
      console.error("[ORAL DEBUG] finalize-analysis ERROR", err);
      console.warn("[oral] finalize-analysis failed:", err);
      const msg =
        err instanceof DOMException && err.name === "AbortError"
          ? "Analyse trop lente, veuillez réessayer."
          : err instanceof Error
            ? err.message
            : "Analyse indisponible pour le moment.";
      toast.error("Analyse impossible", { description: msg });
      // Permettre un retry (refresh ou relance) : ne pas bloquer à vie
      finalizeTriggeredRef.current = false;
      return false;
    } finally {
      window.clearTimeout(t);
      finalizeControllerRef.current = null;
      setIsFinalizingAnalysis(false);
    }
  }, [currentIndex, questions.length]);

  // Fallback : si on arrive en écran "merci" sans finalize déclenché (cas edge), tente quand même.
  useEffect(() => {
    if (!isFinished) return;
    if (finalizeTriggeredRef.current) return;
    void finalizeAnalysisNow();
  }, [isFinished, finalizeAnalysisNow]);

  /** Capture vidéo pour le rapport entreprise (intervalle + anomalies proctoring). */
  const postOralVideoSnapshot = useCallback(
    async (reason: string) => {
      const bearer = getOralInterviewAccessToken();
      if (!bearer?.trim()) return;
      const v = videoRef.current;
      if (!v || v.readyState < 2) return;
      const vw = v.videoWidth || 640;
      const vh = v.videoHeight || 480;
      if (vw < 16 || vh < 16) return;
      try {
        const canvas = document.createElement("canvas");
        canvas.width = vw;
        canvas.height = vh;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(v, 0, 0, vw, vh);
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob((b) => resolve(b), "image/jpeg", 0.82),
        );
        if (!blob) return;
        const fd = new FormData();
        fd.append("reason", reason.slice(0, 80));
        fd.append("image", new File([blob], "snap.jpg", { type: "image/jpeg" }));
        const jwt = getAccessToken("candidat")?.trim();
        if (!jwt) return;
        await fetch(`${getApiBaseUrl()}/api/oral/snapshot`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${jwt}`,
            [ORAL_SESSION_HEADER]: bearer.trim(),
          },
          body: fd,
        });
      } catch {
        /* ne pas interrompre l’entretien */
      }
    },
    [],
  );

  useEffect(() => {
    if (!proctoringEnabled || !token) return;
    const id = window.setInterval(() => void postOralVideoSnapshot("interval"), 45000);
    void postOralVideoSnapshot("interval");
    return () => clearInterval(id);
  }, [proctoringEnabled, token, postOralVideoSnapshot]);

  const prevWarnCount = useRef(0);
  useEffect(() => {
    if (!proctoringEnabled || !token) {
      prevWarnCount.current = warnings.length;
      return;
    }
    const n = warnings.length;
    if (n < prevWarnCount.current) {
      prevWarnCount.current = n;
      return;
    }
    if (n === prevWarnCount.current) return;
    const added = warnings.slice(prevWarnCount.current);
    prevWarnCount.current = n;
    if (added.some((w) => w.severity === "warn")) {
      void postOralVideoSnapshot("anomaly");
    }
  }, [warnings, proctoringEnabled, token, postOralVideoSnapshot]);

  useEffect(() => {
    const init = async () => {
      if (!token) {
        setLoading(false);
        return;
      }
      setGenError(null);
      let data: Awaited<ReturnType<typeof fetchOralBootstrap>>;
      try {
        data = await fetchOralBootstrap();
        setOffer(data);
        if (data.candidate_photo_uploaded) {
          setIdentityPhotoConfirmed(true);
        }
      } catch (e) {
        console.error("Bootstrap error:", e);
        setGenError(
          e instanceof Error ? e.message : "Lien d'entretien invalide ou session expirée.",
        );
        setLoading(false);
        return;
      }
      try {
        const gen = (await apiFetch("/api/oral/generate-ai-questions", {
          method: "POST",
          body: JSON.stringify({
            job_title: data.titre_poste,
            keywords: data.departement || "General",
            nb_tech: data.nombre_questions_oral ?? undefined,
          }),
        })) as { questions: string[] };
        const list = gen.questions ?? [];
        setQuestions(list);
        if (list.length === 0) {
          setGenError("Aucune question reçue du serveur (liste vide).");
        }
      } catch (e) {
        console.error("Génération questions error:", e);
        setGenError(
          e instanceof Error
            ? e.message
            : "Impossible de générer les questions (réseau ou serveur).",
        );
      } finally {
        setLoading(false);
      }
    };
    void init();
  }, [token]);

  /** Vérifie l’accès au micro (autorisation) avant de permettre d’enregistrer. */
  useEffect(() => {
    if (loading || !token) return;
    let cancelled = false;
    setMicReady(false);
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          return;
        }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
        if (!cancelled) {
          setMicReady(true);
        }
      } catch {
        if (!cancelled) {
          setMicReady(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loading, token, mediaCheckNonce]);

  const handleUpload = useCallback(
    async (blob: Blob) => {
      if (!offer || isUploading || questions.length === 0 || !token) return;

      setIsUploading(true);
      setJustSaved(false);
      const formData = new FormData();
      formData.append("audio", new File([blob], "answer.webm", { type: "audio/webm" }));
      formData.append("question_order", String(currentIndex + 1));
      if (lastDurationSeconds != null) {
        formData.append("answer_duration_seconds", String(lastDurationSeconds));
      }

      try {
        console.log("[oral] Sending answer...", {
          questionOrder: currentIndex + 1,
          hasToken: Boolean(token?.trim()),
          bytes: blob.size,
        });

        const controller = new AbortController();
        const timeoutMs = 15000;
        const t = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
          const res = await apiFetch("/api/oral/save-answer", {
            method: "POST",
            body: formData,
            signal: controller.signal,
          });
          console.log("[oral] save-answer response", res);
        } finally {
          window.clearTimeout(t);
        }

        setJustSaved(true);
        if (currentIndex < questions.length - 1) {
          window.setTimeout(() => {
            setJustSaved(false);
            setCurrentIndex((prev) => prev + 1);
          }, 700);
        } else {
          // Dernière question : finalize-analysis doit partir immédiatement (et une seule fois).
          const ok = await finalizeAnalysisNow();
          // Même si échec, ne pas bloquer l’UI indéfiniment : écran de fin quand même.
          setIsFinished(true);
          if (!ok) {
            // L’utilisateur peut fermer la page ; il pourra relancer plus tard via un retry (refresh).
            toast.message("Analyse en cours", {
              description: "L’analyse peut prendre du temps. Vous pouvez réessayer plus tard si besoin.",
            });
          }
        }
      } catch (e) {
        console.error("Upload error", e);
        const msg =
          e instanceof DOMException && e.name === "AbortError"
            ? "Le serveur met trop de temps à répondre. Vérifiez votre connexion puis réessayez."
            : "Erreur lors de l'envoi de l'enregistrement, veuillez réessayer.";
        toast.error("Envoi impossible", { description: msg });
      } finally {
        setIsUploading(false);
      }
    },
    [offer, token, questions, currentIndex, isUploading, lastDurationSeconds, finalizeAnalysisNow],
  );

  useEffect(() => {
    if (audioBlob && !isRecording && audioBlob !== lastProcessedBlob.current) {
      lastProcessedBlob.current = audioBlob;
      void handleUpload(audioBlob);
    }
  }, [audioBlob, isRecording, handleUpload]);

  const inPreparation = prepSecondsLeft != null && prepSecondsLeft > 0;
  const canUseStopButton = isRecording && !isUploading && !isFinalizingAnalysis;
  const mainButtonDisabled =
    !isRecording &&
    (isUploading || isFinalizingAnalysis || inPreparation || !mediaReady || questions.length === 0 || !!genError);

  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-primary/5 px-4">
        <div className="flex flex-col items-center gap-4">
          <div className="h-14 w-14 animate-pulse rounded-xl border border-primary/20 bg-primary/5 card-shadow" />
          <p className="text-sm font-medium text-muted-foreground">Chargement de l&apos;entretien…</p>
        </div>
      </div>
    );

  if (!token) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-background to-primary/5 p-6 text-center">
        <div className="w-full max-w-lg rounded-xl border border-primary/20 bg-card p-8 shadow-lg">
          <h1 className="text-xl font-semibold text-primary">Accès à l&apos;entretien</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Aucune session valide. Ouvrez le lien personnel reçu par e-mail après votre test écrit, ou
            rechargez la page si vous venez de cliquer sur le lien d&apos;invitation.
          </p>
        </div>
      </div>
    );
  }

  const needsPreInterviewPhoto =
    questions.length > 0 && !genError && !identityPhotoConfirmed;

  if (!loading && needsPreInterviewPhoto) {
    const takePhoto = () => {
      const v = identityVideoRef.current;
      if (!v || v.readyState < 2) return;
      const vw = v.videoWidth || 640;
      const vh = v.videoHeight || 480;
      if (vw < 16 || vh < 16) return;
      const canvas = document.createElement("canvas");
      canvas.width = vw;
      canvas.height = vh;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(v, 0, 0, vw, vh);
      setCapturedIdentityDataUrl(canvas.toDataURL("image/jpeg", 0.8));
      setIdentityPhase("preview");
    };

    const retakePhoto = () => {
      setCapturedIdentityDataUrl(null);
      setIdentityPhase("live");
    };

    const confirmPhoto = async () => {
      if (!capturedIdentityDataUrl?.trim() || !token?.trim()) return;
      setIdentityUploading(true);
      try {
        await apiFetch("/api/oral/upload-candidate-photo", {
          method: "POST",
          body: JSON.stringify({
            image_base64: capturedIdentityDataUrl,
            access_token: token,
          }),
        });
        setIdentityPhotoConfirmed(true);
        setIdentityPhase("live");
        setCapturedIdentityDataUrl(null);
        toast.success("Photo enregistrée", {
          description: "Vous pouvez commencer l’entretien.",
        });
      } catch (e) {
        const msg =
          e instanceof Error ? e.message : "Impossible d’enregistrer la photo. Réessayez.";
        toast.error("Envoi de la photo impossible", { description: msg });
      } finally {
        setIdentityUploading(false);
      }
    };

    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-primary/5 p-4 sm:p-8">
        <div className="w-full max-w-lg rounded-2xl border border-primary/20 bg-card p-6 shadow-xl shadow-primary/10 sm:p-8">
          <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/15 text-primary">
            <Camera className="h-6 w-6" aria-hidden />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-primary sm:text-2xl">
            Vérification identité
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Nous allons prendre une photo pour vérifier votre présence.
          </p>

          <div
            className="relative mt-6 aspect-video w-full overflow-hidden rounded-xl border-2 border-primary/30 bg-black shadow-inner"
            aria-live="polite"
          >
            {identityPhase === "live" ? (
              <CameraPreview ref={identityVideoRef} onReadyChange={setIdentityCameraReady} />
            ) : capturedIdentityDataUrl ? (
              <img
                src={capturedIdentityDataUrl}
                alt="Aperçu de votre photo"
                className="h-full w-full object-cover"
              />
            ) : null}
          </div>

          {identityPhase === "live" ? (
            <div className="mt-6 space-y-3">
              <Button
                type="button"
                className="w-full"
                size="lg"
                disabled={!identityCameraReady || identityUploading}
                onClick={takePhoto}
              >
                <Camera className="mr-2 h-4 w-4" aria-hidden />
                Prendre photo
              </Button>
              {!identityCameraReady ? (
                <p className="text-center text-xs text-muted-foreground">
                  Autorisez la caméra pour activer le bouton.
                </p>
              ) : null}
            </div>
          ) : (
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                disabled={identityUploading}
                onClick={retakePhoto}
              >
                Reprendre la photo
              </Button>
              <Button
                type="button"
                className="w-full sm:min-w-[240px]"
                size="lg"
                disabled={identityUploading}
                onClick={() => void confirmPhoto()}
              >
                {identityUploading ? "Envoi…" : "Confirmer et commencer l’entretien"}
              </Button>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (isFinished)
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-background to-primary/5 p-6 text-center">
        <div className="w-full max-w-lg rounded-xl border border-primary/20 bg-card p-8 shadow-lg shadow-primary/10 card-shadow">
          <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-success/15 text-success">
            <CheckCircle2 className="h-8 w-8" aria-hidden />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-primary">Merci pour votre participation.</h1>
          <p className="mt-4 text-sm leading-relaxed text-foreground">
            Vos réponses sont enregistrées.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Vous pouvez fermer cette page ; l’analyse détaillée se poursuit côté serveur.
          </p>
          <Button
            type="button"
            className="mt-8 w-full max-w-xs"
            onClick={() => {
              window.close();
              navigate("/", { replace: true });
            }}
          >
            Fermer la page
          </Button>
          <p className="mt-4 text-xs text-muted-foreground">
            Si la fenêtre ne se ferme pas, vous pouvez fermer cet onglet ou quitter le navigateur.
          </p>
        </div>
      </div>
    );

  return (
    <div
      ref={shellRef}
      className="min-h-screen bg-gradient-to-br from-background to-primary/5 p-6 text-foreground sm:p-8"
    >
      <div className="mx-auto max-w-7xl">
        <header className="mb-8 flex flex-col gap-4 rounded-2xl bg-gradient-to-r from-primary to-primary/80 px-4 py-5 text-white shadow-lg shadow-primary/25 sm:mb-10 sm:flex-row sm:items-start sm:justify-between sm:px-6 sm:py-6">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">Entretien oral</h1>
            <p className="mt-1 text-sm text-white/80">
              Poste :{" "}
              <span className="font-semibold text-white">{offer?.titre_poste ?? "—"}</span>
            </p>
            {genError ? (
              <p
                className="mt-4 rounded-xl border border-white/25 bg-black/20 px-4 py-3 text-sm text-white backdrop-blur-sm"
                role="alert"
              >
                {genError}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-start justify-end gap-3 sm:max-w-[min(100%,420px)]">
            {questions.length > 0 && !genError && mediaReady ? (
              <OralInterviewTimer
                phase={timerPhase}
                prepSecondsLeft={prepSecondsLeft}
                answerSecondsLeft={answerSecondsLeft}
                allowedAnswerSeconds={allowedAnswerSeconds}
                className="w-full sm:w-auto"
              />
            ) : null}
            <Badge className="h-9 shrink-0 self-center border-0 bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-md ring-2 ring-white/25 hover:bg-primary/90">
              Question {currentIndex + 1} / {questions.length}
            </Badge>
          </div>
        </header>

        {proctoringEnabled ? (
          <div
            className="mb-6 flex items-start gap-3 rounded-xl border border-warning/50 bg-warning/15 px-4 py-3 text-sm text-foreground shadow-sm"
            role="status"
            aria-live="polite"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden />
            <p className="flex-1 font-medium leading-snug">{TAB_VISIBILITY_MESSAGE}</p>
          </div>
        ) : null}

        {warningsWithoutTab.length > 0 ? (
          <div className="mb-6 space-y-2">
            {warningsWithoutTab.map((w) => (
              <div
                key={w.id}
                className={cn(
                  "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
                  w.severity === "warn"
                    ? "border-warning/50 bg-warning/15 text-foreground"
                    : "border-border bg-muted/60 text-foreground",
                )}
                role="status"
              >
                <AlertTriangle
                  className={cn(
                    "mt-0.5 h-5 w-5 shrink-0",
                    w.severity === "warn" ? "text-warning" : "text-muted-foreground",
                  )}
                />
                <p className="flex-1 font-medium leading-snug">{w.message}</p>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                  onClick={() => dismissWarning(w.id)}
                  aria-label="Fermer l’avertissement"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        ) : null}

        {!loading && questions.length > 0 && !genError && !mediaReady ? (
          <div
            className="mb-6 rounded-xl border border-amber-500/50 bg-amber-500/10 px-4 py-4 text-sm text-foreground shadow-sm"
            role="status"
            aria-live="polite"
          >
            <p className="font-semibold text-amber-950 dark:text-amber-100">
              Autorisez la caméra et le micro pour commencer l&apos;entretien
            </p>
            <p className="mt-1 text-muted-foreground">
              L&apos;enregistrement des réponses est désactivé tant que les deux périphériques ne sont pas
              accessibles.
            </p>
            <ul className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-6">
              <li className="flex items-center gap-2">
                {cameraReady ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden />
                ) : (
                  <XCircle className="h-5 w-5 shrink-0 text-destructive" aria-hidden />
                )}
                <Video className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span>Caméra {cameraReady ? "active" : "non disponible"}</span>
              </li>
              <li className="flex items-center gap-2">
                {micReady ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden />
                ) : (
                  <XCircle className="h-5 w-5 shrink-0 text-destructive" aria-hidden />
                )}
                <Mic className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span>Micro {micReady ? "autorisé" : "non autorisé"}</span>
              </li>
            </ul>
            {!micReady ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => setMediaCheckNonce((n) => n + 1)}
              >
                Réessayer le micro
              </Button>
            ) : null}
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1.7fr] lg:items-center lg:gap-8">
          <div className="flex w-full min-w-0 justify-center lg:justify-center">
            <div
              className={cn(
                "relative w-full max-w-[520px] overflow-hidden rounded-xl border-2 border-primary/30 bg-black",
                "aspect-video shadow-[0_0_20px_hsl(var(--primary)/0.15)]",
                isRecording && "ring-4 ring-primary/40 ring-offset-2 ring-offset-background",
              )}
            >
              <div className="absolute inset-0 z-0 flex min-h-0 w-full min-w-0">
                <CameraPreview ref={videoRef} onReadyChange={setCameraReady} />
              </div>
            </div>
          </div>

          <div className="relative flex min-h-0 w-full min-w-0 flex-col justify-between rounded-xl border border-primary/20 border-l-4 border-l-primary bg-gradient-to-br from-card to-primary/5 p-8 shadow-md">
            <div className="space-y-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-primary">Question</p>
              <h2 className="text-2xl font-semibold leading-snug text-primary lg:text-3xl">
                {questions.length > 0
                  ? `« ${questions[currentIndex]} »`
                  : genError
                    ? "Les questions n'ont pas pu être chargées."
                    : "Préparation de la question…"}
              </h2>
            </div>

            <div className="pt-8">
              <Button
                type="button"
                size="lg"
                variant={isRecording ? "destructive" : "default"}
                onClick={() => {
                  if (isRecording) stopRecording();
                }}
                disabled={isRecording ? !canUseStopButton : mainButtonDisabled}
                title={
                  !isRecording && !mediaReady
                    ? "Autorisez la caméra et le micro dans le navigateur pour enregistrer."
                    : inPreparation
                      ? "La réponse démarre automatiquement après le temps de préparation."
                      : undefined
                }
                className={cn(
                  "h-auto w-full rounded-xl py-6 text-base font-semibold shadow-lg transition-transform",
                  "active:scale-95",
                  !isRecording &&
                    !justSaved &&
                    !inPreparation &&
                    "bg-primary text-white shadow-xl shadow-primary/30 hover:scale-[1.02] hover:bg-primary/90",
                  isRecording &&
                    "animate-pulse bg-destructive text-destructive-foreground shadow-xl shadow-destructive/30 hover:scale-[1.02] hover:bg-destructive/90",
                  !isRecording &&
                    justSaved &&
                    "bg-success text-success-foreground shadow-xl hover:scale-[1.02] hover:bg-success/90",
                  !isRecording &&
                    inPreparation &&
                    "cursor-not-allowed bg-muted text-muted-foreground opacity-90 shadow-none hover:scale-100 hover:bg-muted",
                )}
              >
                {isUploading
                  ? "Envoi…"
                  : isFinalizingAnalysis
                    ? "Analyse en cours…"
                  : isRecording
                    ? "Terminer"
                    : justSaved
                      ? "Envoyé ✓"
                      : inPreparation
                        ? "Préparation…"
                        : "Enregistrement automatique"}
              </Button>
              <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
                <Mic className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden />
                <span>
                  {isRecording
                    ? "Enregistrement en cours — fin automatique à la fin du temps imparti."
                    : isUploading
                      ? "Envoi au serveur…"
                      : isFinalizingAnalysis
                        ? "Analyse en cours…"
                      : justSaved
                        ? "Réponse enregistrée"
                        : !mediaReady
                          ? "Autorisez la caméra et le micro pour enregistrer."
                          : inPreparation
                            ? "Temps de préparation — l’enregistrement démarre ensuite tout seul."
                            : "Répondez naturellement ; le micro s’active après le compte à rebours."}
                </span>
              </p>

              {isRecording ? (
                <p className="mt-4 text-center text-xs font-medium uppercase tracking-wide text-destructive animate-bounce">
                  Parlez maintenant…
                </p>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InterviewPage;
