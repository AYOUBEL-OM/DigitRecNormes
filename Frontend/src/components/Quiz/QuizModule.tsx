import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import Editor from "@monaco-editor/react";
import confetti from "canvas-confetti";
import {
  AlertCircle,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RotateCcw,
  Send,
  Timer,
  Trophy,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api, QUIZ_SESSION_KEY } from "@/services/axios";

import { QuizCard } from "./QuizCard";
import type { Question } from "./types";

export type QuizModuleProps = {
  /** Identifiant UUID de l’offre ; sinon lu depuis l’URL (`offreId` ou `id`). */
  offreId?: string;
};

type QuizKind = "qcm" | "exercice";

const QUESTIONS_PER_PAGE = 5;

/** Durée du test en secondes (QCM : 10 min, exercice : 40 min). */
const QCM_TIME_SEC = 10 * 60;
const EXERCISE_TIME_SEC = 40 * 60;

type IdentityGateState = "pending" | "loading" | "verified" | "error";

type PersistState = "idle" | "loading" | "ok" | "error";

type QuizConfigResponse = {
  offre_id: string;
  title: string | null;
  profile: string | null;
  level: string | null;
  type_examens_ecrit: string | null;
  quiz_type: string;
  qcm_question_count?: number;
};

type GeneratePayload = {
  quiz_type?: string;
  questions?: Question[];
  title?: string;
  description?: string;
  initial_code?: string;
  [key: string]: unknown;
};

type VerifyState = "idle" | "loading" | "ok" | "error";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidOffreUuid(s: string): boolean {
  return UUID_RE.test(s.trim());
}

function resolveOffreId(propId: string | undefined, params: Record<string, string | undefined>) {
  return (propId?.trim() || params.offreId?.trim() || params.id?.trim()) ?? "";
}

function normalizeQuizType(payload: GeneratePayload): QuizKind | null {
  const t = payload.quiz_type;
  if (t === "qcm" || t === "exercice") return t;
  if (Array.isArray(payload.questions)) {
    return "qcm";
  }
  if (payload.title != null && payload.description != null) {
    return "exercice";
  }
  return null;
}

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg?: string }).msg) : String(x)))
      .join(", ");
  }
  return "";
}

function isQuizKind(v: string | undefined): v is QuizKind {
  return v === "qcm" || v === "exercice";
}

export function QuizModule({ offreId: offreIdProp }: QuizModuleProps) {
  const params = useParams<{ offreId?: string; id?: string }>();
  const offreId = useMemo(
    () => resolveOffreId(offreIdProp, params as Record<string, string | undefined>),
    [offreIdProp, params],
  );

  const [verifyState, setVerifyState] = useState<VerifyState>("idle");
  const [offreConfig, setOffreConfig] = useState<QuizConfigResponse | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verifyHttpStatus, setVerifyHttpStatus] = useState<number | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Type renvoyé par la génération (aligné sur ``quiz_type`` de l’offre). */
  const [activeKind, setActiveKind] = useState<QuizKind | null>(null);

  const [questions, setQuestions] = useState<Question[]>([]);
  const [exercice, setExercice] = useState<{
    title?: string;
    description?: string;
    initial_code?: string;
  } | null>(null);

  const [userAnswers, setUserAnswers] = useState<Record<number, string>>({});
  const [currentPage, setCurrentPage] = useState(0);
  const [userCode, setUserCode] = useState("");
  const [score, setScore] = useState<number | null>(null);
  const [evaluation, setEvaluation] = useState<{ score?: number; feedback?: string } | null>(null);

  /** Vérification identité candidat (email / mot de passe) avant génération du test. */
  const [identityGate, setIdentityGate] = useState<IdentityGateState>("pending");
  const [identityEmail, setIdentityEmail] = useState("");
  const [identityPassword, setIdentityPassword] = useState("");
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [idCandidature, setIdCandidature] = useState<string | null>(null);

  const [persistState, setPersistState] = useState<PersistState>("idle");
  const [persistError, setPersistError] = useState<string | null>(null);

  const [quizSessionId, setQuizSessionId] = useState(0);
  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(null);

  const qcmFinalizedRef = useRef(false);
  const exerciseSubmitDoneRef = useRef(false);
  const exerciseEvaluatingRef = useRef(false);
  const expireHandledRef = useRef(false);

  useEffect(() => {
    const oid = offreId.trim();
    if (!oid) {
      setVerifyState("idle");
      setOffreConfig(null);
      setVerifyError(null);
      setVerifyHttpStatus(null);
      return;
    }
    if (!isValidOffreUuid(oid)) {
      setVerifyState("error");
      setOffreConfig(null);
      setVerifyHttpStatus(400);
      setVerifyError("Lien invalide ou expiré");
      return;
    }

    let cancelled = false;
    setVerifyState("loading");
    setVerifyError(null);
    setVerifyHttpStatus(null);
    setOffreConfig(null);

    api
      .get<QuizConfigResponse>(`/api/quiz/config/${oid}`)
      .then(({ data }) => {
        if (cancelled) return;
        setOffreConfig(data);
        setVerifyState("ok");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setVerifyState("error");
        let msg = "";
        let status: number | null = null;
        if (axios.isAxiosError(e)) {
          status = e.response?.status ?? null;
          msg = formatApiDetail(e.response?.data?.detail);
        }
        setVerifyHttpStatus(status);
        setVerifyError(msg || "Impossible de vérifier l’offre.");
      });

    return () => {
      cancelled = true;
    };
  }, [offreId]);

  const applyGeneratePayload = useCallback((payload: GeneratePayload) => {
    const kind = normalizeQuizType(payload);
    if (!kind) {
      setError("Réponse serveur : type de quiz non reconnu (quiz_type attendu).");
      setActiveKind(null);
      setQuestions([]);
      setExercice(null);
      return;
    }

    setActiveKind(kind);
    setError(null);

    if (kind === "qcm") {
      setExercice(null);
      setEvaluation(null);
      setUserCode("");
      setCurrentPage(0);
      if (Array.isArray(payload.questions)) {
        setQuestions(payload.questions);
      } else {
        setQuestions([]);
        setError("Format QCM non reconnu (champ questions manquant).");
      }
    } else {
      setQuestions([]);
      setScore(null);
      setUserAnswers({});
      setExercice({
        title: typeof payload.title === "string" ? payload.title : undefined,
        description: typeof payload.description === "string" ? payload.description : undefined,
        initial_code: typeof payload.initial_code === "string" ? payload.initial_code : undefined,
      });
      setUserCode(typeof payload.initial_code === "string" ? payload.initial_code : "");
      setEvaluation(null);
    }
  }, []);

  const persistTestEcrit = useCallback(
    async (finalScore: number) => {
      if (!idCandidature) {
        setPersistState("error");
        setPersistError("Identifiant de candidature manquant. Vérifiez votre identité.");
        return;
      }
      setPersistState("loading");
      setPersistError(null);
      try {
        await api.post("/api/quiz/tests-ecrits", {
          id_candidature: idCandidature,
          score_ecrit: finalScore,
          status_reussite: finalScore >= 70,
        });
        setPersistState("ok");
      } catch (e: unknown) {
        setPersistState("error");
        let msg = "Enregistrement du résultat impossible.";
        if (axios.isAxiosError(e)) {
          msg = formatApiDetail(e.response?.data?.detail) || msg;
        }
        setPersistError(msg);
      }
    },
    [idCandidature],
  );

  const handleIdentitySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!offreId.trim() || !isValidOffreUuid(offreId)) {
      setIdentityError("Offre invalide.");
      return;
    }
    setIdentityGate("loading");
    setIdentityError(null);
    try {
      const { data } = await api.post<{
        id_candidature: string;
        access_token: string;
      }>("/api/quiz/verify-for-test", {
        email: identityEmail.trim(),
        mot_de_passe: identityPassword,
        offre_id: offreId.trim(),
      });
      setIdCandidature(data.id_candidature);
      sessionStorage.setItem(QUIZ_SESSION_KEY, data.access_token);
      setIdentityPassword("");
      setIdentityGate("verified");
    } catch (err: unknown) {
      setIdentityGate("error");
      let msg = "Identifiants incorrects ou accès refusé.";
      if (axios.isAxiosError(err)) {
        msg = formatApiDetail(err.response?.data?.detail) || msg;
      }
      setIdentityError(msg);
    }
  };

  useEffect(() => {
    return () => {
      sessionStorage.removeItem(QUIZ_SESSION_KEY);
    };
  }, []);

  useEffect(() => {
    qcmFinalizedRef.current = false;
    exerciseSubmitDoneRef.current = false;
    exerciseEvaluatingRef.current = false;
    expireHandledRef.current = false;
  }, [quizSessionId]);

  /** Compte à rebours pendant une session de test active. */
  useEffect(() => {
    const qcmActive = activeKind === "qcm" && questions.length > 0 && score === null;
    const exActive = activeKind === "exercice" && exercice && evaluation === null;
    if (!qcmActive && !exActive) {
      setSecondsRemaining(null);
      return;
    }
    const total = qcmActive ? QCM_TIME_SEC : EXERCISE_TIME_SEC;
    setSecondsRemaining(total);
    const id = window.setInterval(() => {
      setSecondsRemaining((s) => {
        if (s === null || s <= 1) return 0;
        return s - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [quizSessionId, activeKind, questions.length, score, evaluation, exercice]);

  /** Anti-triche pendant le test : clic droit, copier/coller, raccourcis capture / impression. */
  useEffect(() => {
    const qcmActive = activeKind === "qcm" && questions.length > 0 && score === null;
    const exActive = activeKind === "exercice" && exercice && evaluation === null;
    if (!qcmActive && !exActive) return;

    const blockMenu = (ev: MouseEvent) => {
      ev.preventDefault();
    };
    const blockClipboard = (ev: ClipboardEvent) => {
      ev.preventDefault();
    };
    const blockKeys = (ev: KeyboardEvent) => {
      const k = ev.key;
      if (ev.ctrlKey && (k === "p" || k === "P" || k === "v" || k === "V" || k === "c" || k === "C" || k === "x" || k === "X")) {
        ev.preventDefault();
      }
      if (ev.metaKey && (k === "p" || k === "P")) ev.preventDefault();
      if (k === "PrintScreen") ev.preventDefault();
      if (ev.shiftKey && (k === "s" || k === "S") && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
      }
    };

    document.addEventListener("contextmenu", blockMenu);
    document.addEventListener("copy", blockClipboard);
    document.addEventListener("cut", blockClipboard);
    document.addEventListener("paste", blockClipboard);
    window.addEventListener("keydown", blockKeys, true);
    return () => {
      document.removeEventListener("contextmenu", blockMenu);
      document.removeEventListener("copy", blockClipboard);
      document.removeEventListener("cut", blockClipboard);
      document.removeEventListener("paste", blockClipboard);
      window.removeEventListener("keydown", blockKeys, true);
    };
  }, [activeKind, questions.length, score, exercice, evaluation]);

  const handleGenerate = async () => {
    if (!offreId) {
      setError("Identifiant d’offre manquant (prop ou URL).");
      return;
    }
    if (verifyState !== "ok") {
      setError("L’offre doit être validée avant de générer le test.");
      return;
    }
    if (identityGate !== "verified" || !idCandidature) {
      setError("Identité candidat requise : connectez-vous avant de lancer le test.");
      return;
    }

    setLoading(true);
    setError(null);
    setPersistState("idle");
    setPersistError(null);
    setQuestions([]);
    setExercice(null);
    setScore(null);
    setUserAnswers({});
    setCurrentPage(0);
    setEvaluation(null);
    setActiveKind(null);
    setUserCode("");

    try {
      const { data } = await api.get(`/api/generate/${offreId}`);
      const payload = (typeof data === "string" ? JSON.parse(data) : data) as GeneratePayload;
      applyGeneratePayload(payload);
      setQuizSessionId((x) => x + 1);
    } catch (e: unknown) {
      let msg = "";
      if (axios.isAxiosError(e)) {
        msg = formatApiDetail(e.response?.data?.detail);
      }
      setError(
        msg || "Erreur de génération. Vérifiez la connexion au backend, l’ID d’offre et type_examens_ecrit.",
      );
    } finally {
      setLoading(false);
    }
  };

  const calculateQcmScore = useCallback(() => {
    if (qcmFinalizedRef.current) return;
    qcmFinalizedRef.current = true;
    let correct = 0;
    questions.forEach((q, idx) => {
      if (userAnswers[idx] === q.answer) correct++;
    });
    const finalScore = questions.length ? Math.round((correct / questions.length) * 100) : 0;
    setScore(finalScore);
    if (finalScore >= 70) confetti();
    void persistTestEcrit(finalScore);
  }, [questions, userAnswers, persistTestEcrit]);

  const submitCode = useCallback(async () => {
    if (!exercice?.description) return;
    if (exerciseSubmitDoneRef.current || exerciseEvaluatingRef.current) return;
    exerciseEvaluatingRef.current = true;
    setLoading(true);
    try {
      const { data } = await api.post("/api/evaluate", {
        code: userCode,
        consigne: exercice.description,
      });
      const result = typeof data === "string" ? JSON.parse(data) : data;
      exerciseSubmitDoneRef.current = true;
      setEvaluation(result);
      if (typeof result.score === "number" && result.score >= 70) confetti();
      const sc = typeof result.score === "number" ? result.score : 0;
      void persistTestEcrit(sc);
    } catch {
      exerciseSubmitDoneRef.current = false;
      setError("Erreur lors de l’évaluation de la réponse.");
    } finally {
      exerciseEvaluatingRef.current = false;
      setLoading(false);
    }
  }, [exercice, userCode, persistTestEcrit]);

  /** Fin de temps : soumission automatique (une seule fois par session). */
  useEffect(() => {
    if (secondsRemaining !== 0) return;
    if (expireHandledRef.current) return;
    if (quizSessionId === 0) return;
    const qcmActive = activeKind === "qcm" && questions.length > 0 && score === null;
    const exActive = activeKind === "exercice" && exercice && evaluation === null;
    if (!qcmActive && !exActive) return;
    expireHandledRef.current = true;
    if (qcmActive) {
      calculateQcmScore();
    } else if (exActive) {
      void submitCode();
    }
  }, [
    secondsRemaining,
    quizSessionId,
    activeKind,
    questions.length,
    score,
    evaluation,
    exercice,
    calculateQcmScore,
    submitCode,
  ]);

  const missingId = !offreId.trim();
  const malformedUuid = Boolean(offreId.trim() && !isValidOffreUuid(offreId));
  const configNotFound =
    verifyState === "error" &&
    (verifyHttpStatus === 404 ||
      verifyHttpStatus === 422 ||
      /offre introuvable/i.test(verifyError || ""));
  const showInvalidLinkScreen = missingId || malformedUuid || configNotFound;

  const expectedKind: QuizKind | null =
    activeKind ??
    (offreConfig?.quiz_type && isQuizKind(offreConfig.quiz_type) ? offreConfig.quiz_type : null);

  const canGenerate = !missingId && verifyState === "ok" && identityGate === "verified" && Boolean(idCandidature);

  const testInProgress =
    (activeKind === "qcm" && questions.length > 0 && score === null) ||
    (activeKind === "exercice" && exercice !== null && evaluation === null);

  const showTimerBar = secondsRemaining !== null && testInProgress;

  const awaitingConfig =
    !missingId &&
    isValidOffreUuid(offreId) &&
    verifyState !== "ok" &&
    verifyState !== "error";

  const totalQcmPages = Math.max(1, Math.ceil(questions.length / QUESTIONS_PER_PAGE));
  const pageStart = currentPage * QUESTIONS_PER_PAGE;
  const pageQuestions = questions.slice(pageStart, pageStart + QUESTIONS_PER_PAGE);
  const answeredCount = Object.keys(userAnswers).length;

  const formatCountdown = (sec: number) => {
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  };

  if (showInvalidLinkScreen) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6 py-16 font-sans">
        <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 text-center shadow-[var(--card-shadow)]">
          <AlertCircle className="mx-auto mb-4 h-12 w-12 text-destructive" aria-hidden />
          <h1 className="text-xl font-semibold tracking-tight text-card-foreground">
            Lien invalide ou expiré
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Ce lien de test n’est plus valide ou l’identifiant est incorrect. Contactez l’équipe de recrutement
            pour obtenir une nouvelle invitation.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      {showTimerBar ? (
        <div
          className="fixed left-0 right-0 top-0 z-50 flex items-center justify-center gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80"
          role="timer"
          aria-live="polite"
        >
          <Timer className="h-5 w-5 shrink-0 text-primary" aria-hidden />
          <span className="font-mono text-lg font-semibold tabular-nums text-foreground">
            {formatCountdown(secondsRemaining ?? 0)}
          </span>
          <span className="text-xs text-muted-foreground">Temps restant</span>
        </div>
      ) : null}

      {verifyState === "ok" && offreConfig && identityGate !== "verified" ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 px-4 py-8"
          role="dialog"
          aria-modal="true"
          aria-labelledby="quiz-verify-title"
        >
          <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-xl">
            <h2 id="quiz-verify-title" className="text-lg font-semibold text-card-foreground">
              Vérification candidat
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Indiquez l’email et le mot de passe du compte avec lequel vous avez postulé à cette offre.
            </p>
            <form onSubmit={(e) => void handleIdentitySubmit(e)} className="mt-6 space-y-4">
              <div className="space-y-2 text-left">
                <Label htmlFor="quiz-email">Email</Label>
                <Input
                  id="quiz-email"
                  type="email"
                  autoComplete="email"
                  value={identityEmail}
                  onChange={(e) => setIdentityEmail(e.target.value)}
                  required
                  disabled={identityGate === "loading"}
                />
              </div>
              <div className="space-y-2 text-left">
                <Label htmlFor="quiz-password">Mot de passe</Label>
                <Input
                  id="quiz-password"
                  type="password"
                  autoComplete="current-password"
                  value={identityPassword}
                  onChange={(e) => setIdentityPassword(e.target.value)}
                  required
                  disabled={identityGate === "loading"}
                />
              </div>
              {identityError ? <p className="text-sm text-destructive">{identityError}</p> : null}
              <Button type="submit" className="w-full rounded-2xl" disabled={identityGate === "loading"}>
                {identityGate === "loading" ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : null}
                Valider et continuer
              </Button>
            </form>
          </div>
        </div>
      ) : null}

    <div className={`min-h-screen bg-background px-4 py-8 font-sans text-foreground ${showTimerBar ? "pt-16" : ""}`}>
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 text-center">
          <div className="mb-4 inline-flex rounded-2xl bg-primary p-3 shadow-lg shadow-primary/20">
            <BrainCircuit className="h-8 w-8 text-primary-foreground" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
            Digit<span className="text-primary">REC</span> — Test écrit
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Identifiez-vous avec votre compte candidat (email et mot de passe) pour lancer le test.
          </p>
          {offreId ? (
            <p className="mt-3 font-mono text-xs text-muted-foreground">
              Offre : <span className="text-foreground">{offreId}</span>
            </p>
          ) : null}
          {expectedKind ? (
            <div className="mt-4 flex justify-center">
              <Badge variant="secondary" className="text-xs uppercase tracking-wide">
                {activeKind ? "Test en cours — " : "Format prévu — "}
                {expectedKind === "qcm" ? "QCM" : "Exercice écrit"}
              </Badge>
            </div>
          ) : null}
        </div>

        {!missingId && awaitingConfig ? (
          <div className="mx-auto mb-8 max-w-2xl rounded-xl border border-border bg-card p-6 shadow-[var(--card-shadow)]">
            <p className="mb-4 text-sm font-medium text-muted-foreground">Vérification de l’offre…</p>
            <Skeleton className="mb-2 h-4 w-full max-w-md" />
            <Skeleton className="h-4 w-full max-w-xs" />
          </div>
        ) : null}

        {!missingId && verifyState === "error" && verifyError && !configNotFound ? (
          <div className="mx-auto mb-8 flex max-w-2xl items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive shadow-sm">
            <AlertCircle className="h-6 w-6 shrink-0" />
            <span className="text-sm font-semibold">{verifyError}</span>
          </div>
        ) : null}

        {!missingId && verifyState === "ok" && offreConfig ? (
          <div className="mx-auto mb-8 max-w-2xl rounded-xl border border-border bg-card p-6 text-left shadow-[var(--card-shadow)]">
            <h2 className="text-lg font-semibold text-card-foreground">
              {offreConfig.title || "Offre validée"}
            </h2>
            {offreConfig.profile ? (
              <p className="mt-2 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Profil : </span>
                {offreConfig.profile}
              </p>
            ) : null}
            {offreConfig.level ? (
              <p className="mt-1 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Niveau : </span>
                {offreConfig.level}
              </p>
            ) : null}
            <p className="mt-3 text-xs text-muted-foreground">
              Type d’examen (offre) :{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">
                {offreConfig.type_examens_ecrit ?? "—"}
              </code>
              {offreConfig.quiz_type === "qcm" && typeof offreConfig.qcm_question_count === "number" ? (
                <>
                  {" "}
                  · QCM :{" "}
                  <span className="text-foreground">{offreConfig.qcm_question_count}</span> question
                  {offreConfig.qcm_question_count > 1 ? "s" : ""} prévues
                </>
              ) : null}
            </p>
          </div>
        ) : null}

        {!missingId && verifyState === "ok" && identityGate === "verified" ? (
          <div className="mx-auto mb-6 flex max-w-2xl justify-center">
            <Badge
              variant="secondary"
              className="border border-[hsl(var(--success))]/40 bg-[hsl(var(--success))]/15 text-xs uppercase tracking-wide text-[hsl(var(--success))]"
            >
              Identité candidat vérifiée
            </Badge>
          </div>
        ) : null}

        <div className="mx-auto mb-10 flex max-w-xl flex-col items-stretch gap-3 sm:flex-row sm:justify-center">
          <Button
            type="button"
            size="lg"
            className="rounded-2xl px-10 font-semibold"
            disabled={loading || !canGenerate}
            onClick={handleGenerate}
          >
            {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
            Générer le test
          </Button>
        </div>

        {error ? (
          <div className="mx-auto mb-8 flex max-w-3xl items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive">
            <AlertCircle className="h-6 w-6 shrink-0" />
            <span className="text-sm font-semibold">{error}</span>
          </div>
        ) : null}

        {activeKind === "qcm" && questions.length > 0 && score === null ? (
          <div className="mx-auto max-w-4xl animate-in fade-in slide-in-from-bottom-4 space-y-2 duration-300">
            {pageQuestions.map((q, localIdx) => {
              const globalIdx = pageStart + localIdx;
              return (
                <QuizCard
                  key={globalIdx}
                  q={q}
                  index={globalIdx}
                  selectedAnswer={userAnswers[globalIdx] ?? null}
                  onSelect={(qIdx, val) => setUserAnswers((prev) => ({ ...prev, [qIdx]: val }))}
                />
              );
            })}

            <div className="flex flex-col items-center gap-6 border-t border-border pt-8">
              <div className="flex flex-wrap items-center justify-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  size="default"
                  className="min-w-[8rem] gap-1 rounded-lg"
                  disabled={currentPage <= 0}
                  onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                  Précédent
                </Button>
                <span className="min-w-[10rem] text-center text-sm tabular-nums text-muted-foreground">
                  Page {Math.min(currentPage + 1, totalQcmPages)} / {totalQcmPages}
                  <span className="mt-1 block text-xs">
                    {answeredCount}/{questions.length} réponse{questions.length > 1 ? "s" : ""}
                  </span>
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="default"
                  className="min-w-[8rem] gap-1 rounded-lg"
                  disabled={currentPage >= totalQcmPages - 1}
                  onClick={() => setCurrentPage((p) => Math.min(totalQcmPages - 1, p + 1))}
                >
                  Suivant
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>

              <Button
                type="button"
                size="lg"
                className="rounded-2xl bg-[hsl(var(--success))] px-12 text-[hsl(var(--success-foreground))] hover:bg-[hsl(var(--success))]/90"
                disabled={answeredCount < questions.length}
                onClick={calculateQcmScore}
              >
                Terminer le test
              </Button>
            </div>
            <div className="pb-12" />
          </div>
        ) : null}

        {score !== null ? (
          <div className="mx-auto max-w-lg animate-in zoom-in rounded-3xl border-4 border-primary bg-card p-10 text-center shadow-xl duration-500">
            <Trophy className="mx-auto mb-4 h-16 w-16 text-[hsl(var(--warning))]" />
            <h2 className="mb-2 text-2xl font-bold">Résultat</h2>
            <div className="mb-4 text-7xl font-black text-primary md:text-8xl">{score}%</div>
            <p className="mb-8 text-lg font-medium text-muted-foreground">
              {score >= 70 ? "Excellent travail !" : "Continuez vos efforts !"}
            </p>
            {persistState === "loading" ? (
              <p className="mb-4 flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Enregistrement du résultat…
              </p>
            ) : null}
            {persistState === "ok" ? (
              <p className="mb-4 text-sm text-[hsl(var(--success))]">Résultat enregistré.</p>
            ) : null}
            {persistState === "error" && persistError ? (
              <p className="mb-4 text-sm text-destructive">{persistError}</p>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              className="gap-2 text-primary"
              onClick={() => {
                setScore(null);
                setPersistState("idle");
                setPersistError(null);
                void handleGenerate();
              }}
            >
              <RotateCcw className="h-4 w-4" />
              Nouveau test
            </Button>
          </div>
        ) : null}

        {activeKind === "exercice" && exercice ? (
          <div className="grid min-h-[520px] animate-in fade-in grid-cols-1 gap-6 duration-300 lg:grid-cols-2 lg:gap-8">
            <div className="overflow-y-auto rounded-xl border border-border bg-card p-8 shadow-[var(--card-shadow)]">
              <Badge variant="secondary" className="mb-4 uppercase tracking-wide">
                Exercice technique
              </Badge>
              <h2 className="mb-4 text-2xl font-bold text-card-foreground">{exercice.title}</h2>
              <div className="prose prose-sm max-w-none text-muted-foreground dark:prose-invert">
                {exercice.description}
              </div>

              {evaluation ? (
                <div className="mt-8 animate-in zoom-in rounded-2xl bg-primary p-6 text-primary-foreground shadow-lg duration-300">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-semibold text-primary-foreground/90">Score IA</span>
                    <span className="text-4xl font-black">{evaluation.score ?? "—"}%</span>
                  </div>
                  <p className="text-sm font-medium leading-snug opacity-95">{evaluation.feedback}</p>
                  {persistState === "loading" ? (
                    <p className="mt-4 flex items-center gap-2 text-sm opacity-90">
                      <Loader2 className="h-4 w-4 animate-spin" /> Enregistrement du résultat…
                    </p>
                  ) : null}
                  {persistState === "ok" ? (
                    <p className="mt-4 text-sm opacity-95">Résultat enregistré.</p>
                  ) : null}
                  {persistState === "error" && persistError ? (
                    <p className="mt-4 text-sm font-medium text-destructive-foreground">{persistError}</p>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="relative flex min-h-[400px] flex-col overflow-hidden rounded-xl border border-border bg-[#1e1e1e] shadow-2xl">
              <div className="flex items-center gap-2 border-b border-[#333] bg-[#2d2d2d] px-4 py-3">
                <div className="h-2.5 w-2.5 rounded-full bg-red-500" />
                <div className="h-2.5 w-2.5 rounded-full bg-yellow-500" />
                <div className="h-2.5 w-2.5 rounded-full bg-green-500" />
                <span className="ml-3 font-mono text-xs text-muted-foreground">solution.py</span>
              </div>
              {!exercice.initial_code || exercice.initial_code.trim() === "" ? (
                <textarea
                  className="min-h-[320px] flex-1 resize-none bg-background p-6 text-base text-foreground outline-none"
                  placeholder="Écrivez votre réponse ici…"
                  value={userCode}
                  onChange={(e) => setUserCode(e.target.value)}
                />
              ) : (
                <Editor
                  height="100%"
                  defaultLanguage="python"
                  theme="vs-dark"
                  value={userCode}
                  onChange={(v) => setUserCode(v || "")}
                  options={{
                    fontSize: 15,
                    minimap: { enabled: false },
                    automaticLayout: true,
                  }}
                />
              )}
              {!evaluation ? (
                <Button
                  type="button"
                  size="lg"
                  className="absolute bottom-6 right-6 z-10 gap-2 rounded-2xl bg-[hsl(var(--success))] text-[hsl(var(--success-foreground))] hover:bg-[hsl(var(--success))]/90"
                  disabled={loading}
                  onClick={() => void submitCode()}
                >
                  {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                  Soumettre
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </div>
    </>
  );
}

export default QuizModule;
