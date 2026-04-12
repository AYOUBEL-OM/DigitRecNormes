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
  Clock,
  Loader2,
  Lock,
  RotateCcw,
  Send,
  Trophy,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/services/axios";

import { QuizCard } from "./QuizCard";
import type { Question } from "./types";

/** Réponse HTTP : objet JSON ou chaîne JSON (éventuellement dans un bloc markdown). */
function parseQuizGeneratePayload(data: unknown): Record<string, unknown> {
  let raw: unknown = data;
  if (typeof raw === "string") {
    raw = JSON.parse(stripMarkdownJsonFence(raw.trim()));
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Réponse serveur : format inattendu.");
  }
  return raw as Record<string, unknown>;
}

function stripMarkdownJsonFence(s: string): string {
  const m = s.match(/^```(?:json)?\s*([\s\S]*?)```$/im);
  return m ? m[1].trim() : s;
}

/**
 * Type de quiz : on suit d’abord `quiz_type` renvoyé par le backend (quiz_service.py),
 * puis repli minimal sur la présence de questions / EXERCICE.
 */
function resolveQuizKind(payload: Record<string, unknown>): QuizKind | null {
  const qtRaw = payload.quiz_type;
  const qt = typeof qtRaw === "string" ? qtRaw.toLowerCase() : "";
  if (qt.includes("exercice")) return "exercice";
  if (qt.includes("qcm")) return "qcm";

  if (payload.EXERCICE && typeof payload.EXERCICE === "object" && !Array.isArray(payload.EXERCICE)) {
    return "exercice";
  }
  if (Array.isArray(payload.questions)) {
    return "qcm";
  }
  if (payload.title != null && payload.description != null) {
    return "exercice";
  }
  return null;
}

export type QuizModuleProps = {
  /** Identifiant UUID de l’offre ; sinon lu depuis l’URL (`offreId` ou `id`). */
  offreId?: string;
};

type QuizKind = "qcm" | "exercice";

const QUESTIONS_PER_PAGE = 5;

/** Durées en secondes : QCM 10 min, exercices 40 min */
const TIMER_QCM_SEC = 10 * 60;
const TIMER_EXERCICE_SEC = 40 * 60;

type QuizConfigResponse = {
  offre_id: string;
  title: string | null;
  profile: string | null;
  level: string | null;
  type_examens_ecrit: string | null;
  quiz_type: string;
  qcm_question_count?: number;
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

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg?: string }).msg) : String(x)))
      .join(", ");
  }
  return "";
}

function formatCountdown(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
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

  const [idCandidature, setIdCandidature] = useState<string | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

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

  const [deadline, setDeadline] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const timerExpireFired = useRef(false);
  const runTimerExpiry = useRef<() => Promise<void>>(async () => {});

  const testEnded =
    (activeKind === "qcm" && score !== null) ||
    (activeKind === "exercice" && evaluation !== null);

  useEffect(() => {
    const oid = offreId.trim();
    if (!oid) return;
    if (!isValidOffreUuid(oid)) {
      setVerifyState("error");
      setVerifyHttpStatus(400);
      setVerifyError("Lien invalide ou expiré");
      return;
    }

    let cancelled = false;
    setVerifyState("loading");
    api
      .get<QuizConfigResponse>(`/api/quiz/config/${oid}`)
      .then(({ data }) => {
        if (!cancelled) {
          setOffreConfig(data);
          setVerifyState("ok");
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setVerifyState("error");
        if (axios.isAxiosError(e)) {
          setVerifyHttpStatus(e.response?.status ?? null);
          setVerifyError(formatApiDetail(e.response?.data?.detail) || "Impossible de vérifier l’offre.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [offreId]);

  const persistScore = useCallback(
    async (value: number) => {
      if (!idCandidature) {
        toast.error("Session invalide", { description: "Identifiant de candidature manquant." });
        return;
      }
      try {
        await api.post("/api/quiz/submit-test-result", {
          id_candidature: idCandidature,
          score_ecrit: value,
        });
        toast.success("Résultat enregistré");
      } catch (e) {
        const msg = axios.isAxiosError(e) ? formatApiDetail(e.response?.data?.detail) : "";
        toast.error("Enregistrement du résultat impossible", {
          description: msg || "Vérifiez votre connexion ou réessayez plus tard.",
        });
      }
    },
    [idCandidature],
  );

  const applyGeneratePayload = useCallback((payload: Record<string, unknown>) => {
    const kind = resolveQuizKind(payload);
    if (!kind) {
      setError("Réponse serveur : type de quiz non reconnu.");
      setActiveKind(null);
      return;
    }

    setActiveKind(kind);
    setError(null);
    setScore(null);
    setEvaluation(null);
    setDeadline(null);
    timerExpireFired.current = false;

    if (kind === "qcm") {
      setExercice(null);
      setUserCode("");
      setUserAnswers({});
      setCurrentPage(0);
      setQuestions(Array.isArray(payload.questions) ? (payload.questions as Question[]) : []);
    } else {
      setQuestions([]);
      const exRoot = payload.EXERCICE ?? payload.exercice ?? payload;
      const exData = exRoot as Record<string, unknown>;
      setExercice({
        title: String(exData.title ?? "Exercice technique"),
        description: String(exData.description ?? ""),
        initial_code: String(exData.initial_code ?? ""),
      });
      setUserCode(String(exData.initial_code ?? ""));
    }
  }, []);

  const handleGenerate = async () => {
    if (!offreId || verifyState !== "ok" || !idCandidature) return;

    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(`/api/generate/${offreId}`);
      const payload = parseQuizGeneratePayload(data);
      applyGeneratePayload(payload);
    } catch (e) {
      const msg =
        e instanceof Error
          ? e.message
          : axios.isAxiosError(e)
            ? formatApiDetail(e.response?.data?.detail)
            : "";
      setError("Erreur de génération. Vérifiez la connexion au backend.");
      toast.error("Génération impossible", {
        description: msg || "Vérifiez la connexion au serveur.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleCandidateLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    const oid = offreId.trim();
    if (!oid || !isValidOffreUuid(oid)) {
      toast.error("Lien d’offre invalide.");
      return;
    }
    setLoginLoading(true);
    setLoginError(null);
    try {
      const { data } = await api.post<{ id_candidature: string }>("/api/quiz/verify-for-test", {
        email: loginEmail.trim(),
        password: loginPassword,
        offre_id: oid,
      });
      setIdCandidature(data.id_candidature);
      toast.success("Connexion confirmée", { description: "Vous pouvez démarrer le test." });
    } catch (err) {
      const msg = axios.isAxiosError(err)
        ? formatApiDetail(err.response?.data?.detail) || "Identifiants incorrects ou accès refusé."
        : "Connexion impossible.";
      setLoginError(msg);
      toast.error("Échec de la connexion", { description: msg });
    } finally {
      setLoginLoading(false);
    }
  };

  /** Démarre le compte à rebours quand un type de test est actif et non terminé */
  useEffect(() => {
    if (!activeKind || testEnded) {
      if (!activeKind) setDeadline(null);
      if (testEnded) setDeadline(null);
      return;
    }
    timerExpireFired.current = false;
    const sec = activeKind === "qcm" ? TIMER_QCM_SEC : TIMER_EXERCICE_SEC;
    setDeadline(Date.now() + sec * 1000);
  }, [activeKind, testEnded]);

  useEffect(() => {
    if (!deadline || testEnded) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [deadline, testEnded]);

  const secondsRemaining = useMemo(() => {
    void tick;
    if (!deadline || testEnded) return null;
    return Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  }, [deadline, testEnded, tick]);

  const finalizeQcmCore = useCallback(async () => {
    let correct = 0;
    questions.forEach((q, idx) => {
      if (userAnswers[idx] === q.answer) correct++;
    });
    const finalScore = questions.length ? Math.round((correct / questions.length) * 100) : 0;
    setScore(finalScore);
    if (finalScore >= 70) confetti();
    await persistScore(finalScore);
  }, [questions, userAnswers, persistScore]);

  const finalizeExerciceForTimer = useCallback(async () => {
    if (!exercice?.description) {
      setEvaluation({ score: 0, feedback: "Temps écoulé sans envoi de code." });
      await persistScore(0);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post("/api/evaluate", {
        code: userCode,
        consigne: exercice.description,
      });
      const result = typeof data === "string" ? JSON.parse(data) : data;
      setEvaluation(result);
      if ((result.score ?? 0) >= 70) confetti();
      await persistScore(result.score ?? 0);
    } catch {
      toast.error("Évaluation automatique impossible", {
        description: "Le temps est écoulé ; enregistrement avec score 0.",
      });
      setEvaluation({ score: 0, feedback: "Erreur d’évaluation." });
      await persistScore(0);
    } finally {
      setLoading(false);
    }
  }, [exercice, userCode, persistScore]);

  runTimerExpiry.current = async () => {
    toast.warning("Temps écoulé", {
      description: "Le test est clos et votre score est enregistré automatiquement.",
    });
    try {
      if (activeKind === "qcm") {
        await finalizeQcmCore();
      } else if (activeKind === "exercice") {
        await finalizeExerciceForTimer();
      }
    } catch {
      toast.error("Erreur lors de la clôture automatique du test.");
    }
  };

  useEffect(() => {
    if (
      secondsRemaining === null ||
      secondsRemaining > 0 ||
      deadline === null ||
      testEnded
    ) {
      return;
    }
    if (timerExpireFired.current) return;
    timerExpireFired.current = true;
    void runTimerExpiry.current();
  }, [secondsRemaining, deadline, testEnded]);

  /** Pendant le test : désactivation clic droit, copier/coller, raccourcis capture / impression */
  useEffect(() => {
    if (!idCandidature || !activeKind) return;

    const block = (e: Event) => {
      e.preventDefault();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "PrintScreen") {
        e.preventDefault();
        toast.message("Capture d’écran non autorisée pendant le test.");
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p") {
        e.preventDefault();
      }
      if (e.shiftKey && (e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === "s" || e.code === "KeyS")) {
        e.preventDefault();
      }
    };

    document.addEventListener("contextmenu", block);
    document.addEventListener("copy", block, true);
    document.addEventListener("cut", block, true);
    document.addEventListener("paste", block, true);
    document.addEventListener("keydown", onKey, true);

    return () => {
      document.removeEventListener("contextmenu", block);
      document.removeEventListener("copy", block, true);
      document.removeEventListener("cut", block, true);
      document.removeEventListener("paste", block, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [idCandidature, activeKind]);

  const handleQcmFinish = async () => {
    await finalizeQcmCore();
  };

  const submitCode = async () => {
    if (!exercice?.description) return;
    setLoading(true);
    try {
      const { data } = await api.post("/api/evaluate", {
        code: userCode,
        consigne: exercice.description,
      });
      const result = typeof data === "string" ? JSON.parse(data) : data;
      setEvaluation(result);
      if ((result.score ?? 0) >= 70) confetti();
      await persistScore(result.score ?? 0);
    } catch (e) {
      const msg = axios.isAxiosError(e) ? formatApiDetail(e.response?.data?.detail) : "";
      setError("Erreur lors de l’évaluation.");
      toast.error("Évaluation impossible", { description: msg || "Réessayez ou contactez le support." });
    } finally {
      setLoading(false);
    }
  };

  const totalQcmPages = Math.max(1, Math.ceil(questions.length / QUESTIONS_PER_PAGE));
  const pageStart = currentPage * QUESTIONS_PER_PAGE;
  const pageQuestions = questions.slice(pageStart, pageStart + QUESTIONS_PER_PAGE);

  if (verifyState === "error" && (verifyHttpStatus === 404 || /introuvable/i.test(verifyError || ""))) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6 text-center">
        <div className="max-w-md rounded-2xl border bg-card p-8 shadow-lg">
          <AlertCircle className="mx-auto mb-4 h-12 w-12 text-destructive" />
          <h1 className="text-xl font-semibold">Lien invalide ou expiré</h1>
          <p className="mt-3 text-muted-foreground text-sm">Contactez l’équipe de recrutement.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background py-8 px-4 text-foreground">
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 text-center">
          <div className="mb-4 inline-flex rounded-2xl bg-primary p-3 shadow-lg">
            <BrainCircuit className="h-8 w-8 text-primary-foreground" />
          </div>
          <h1 className="text-3xl font-bold md:text-4xl">
            Test écrit
          </h1>
          {activeKind && (
            <Badge variant="secondary" className="mt-4 uppercase">
              Test en cours — {activeKind}
            </Badge>
          )}
        </div>

        {verifyState === "ok" && !idCandidature && (
          <div className="mx-auto mb-8 max-w-md rounded-xl border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Lock className="h-4 w-4" />
              Connexion candidat requise
            </div>
            <form onSubmit={handleCandidateLogin} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="quiz-email">E-mail</Label>
                <Input
                  id="quiz-email"
                  type="email"
                  autoComplete="email"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                  required
                  disabled={loginLoading}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="quiz-password">Mot de passe</Label>
                <Input
                  id="quiz-password"
                  type="password"
                  autoComplete="current-password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  required
                  disabled={loginLoading}
                />
              </div>
              {loginError && (
                <p className="text-sm text-destructive" role="alert">
                  {loginError}
                </p>
              )}
              <Button type="submit" className="w-full rounded-xl" disabled={loginLoading}>
                {loginLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Valider et continuer
              </Button>
            </form>
          </div>
        )}

        {verifyState === "ok" && idCandidature && !activeKind && (
          <div className="mx-auto mb-8 max-w-2xl rounded-xl border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">{offreConfig?.title || "Offre validée"}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {offreConfig?.profile} | {offreConfig?.level}
            </p>
            <Button onClick={handleGenerate} disabled={loading} className="mt-6 w-full rounded-xl">
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Commencer le test
            </Button>
          </div>
        )}

        {error && (
          <div className="mx-auto mb-6 flex max-w-3xl items-center gap-3 rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-destructive">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <span className="text-sm font-medium">{error}</span>
          </div>
        )}

        {activeKind && secondsRemaining !== null && !testEnded && (
          <div className="mx-auto mb-6 flex max-w-3xl items-center justify-center gap-3 rounded-xl border bg-muted/50 px-4 py-3 text-sm font-medium">
            <Clock className="h-5 w-5 text-primary" />
            <span>Temps restant : {formatCountdown(secondsRemaining)}</span>
            <span className="text-muted-foreground">
              ({activeKind === "qcm" ? "QCM 10 min" : "Exercice 40 min"})
            </span>
          </div>
        )}

        {/* --- SECTION QCM --- */}
        {activeKind === "qcm" && score === null && (
          <div className="mx-auto max-w-4xl space-y-4">
            {pageQuestions.map((q, i) => (
              <QuizCard
                key={pageStart + i}
                q={q}
                index={pageStart + i}
                selectedAnswer={userAnswers[pageStart + i] ?? null}
                onSelect={(idx, val) => setUserAnswers((p) => ({ ...p, [idx]: val }))}
              />
            ))}
            <div className="mt-8 flex flex-col items-center gap-6">
              <div className="flex items-center gap-4">
                <Button variant="outline" disabled={currentPage === 0} onClick={() => setCurrentPage((p) => p - 1)}>
                  <ChevronLeft className="mr-1 h-4 w-4" /> Précédent
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {currentPage + 1} / {totalQcmPages}
                </span>
                <Button
                  variant="outline"
                  disabled={currentPage >= totalQcmPages - 1}
                  onClick={() => setCurrentPage((p) => p + 1)}
                >
                  Suivant <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
              <Button
                size="lg"
                className="rounded-2xl bg-green-600 px-12 text-white hover:bg-green-700"
                disabled={Object.keys(userAnswers).length < questions.length}
                onClick={() => void handleQcmFinish()}
              >
                Terminer le test
              </Button>
            </div>
          </div>
        )}

        {/* --- SECTION RESULTAT QCM --- */}
        {score !== null && activeKind === "qcm" && (
          <div className="mx-auto max-w-md rounded-3xl border-4 border-primary bg-card p-10 text-center shadow-2xl">
            <Trophy className="mx-auto mb-4 h-16 w-16 text-yellow-500" />
            <h2 className="text-2xl font-bold">Votre score</h2>
            <div className="my-4 text-7xl font-black text-primary">{score}%</div>
            <Button variant="ghost" className="mt-4 gap-2" onClick={() => window.location.reload()}>
              <RotateCcw className="h-4 w-4" /> Recommencer
            </Button>
          </div>
        )}

        {/* --- SECTION EXERCICE --- */}
        {activeKind === "exercice" && exercice && (
          <div className="grid min-h-[500px] grid-cols-1 gap-8 lg:grid-cols-2">
            <div className="overflow-y-auto rounded-xl border bg-card p-8 shadow-sm">
              <Badge className="mb-4">EXERCICE</Badge>
              <h2 className="mb-4 text-2xl font-bold">{exercice.title}</h2>
              <div className="prose prose-sm whitespace-pre-wrap text-muted-foreground dark:prose-invert">
                {exercice.description}
              </div>
              {evaluation && (
                <div className="mt-8 rounded-2xl bg-primary p-6 text-primary-foreground">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-bold">Score IA</span>
                    <span className="text-3xl font-black">{evaluation.score}%</span>
                  </div>
                  <p className="text-sm opacity-90">{evaluation.feedback}</p>
                </div>
              )}
            </div>

            <div className="relative flex flex-col overflow-hidden rounded-xl border bg-[#1e1e1e] shadow-2xl">
              <div className="flex items-center gap-2 border-b border-[#333] bg-[#2d2d2d] px-4 py-2">
                <div className="flex gap-1.5">
                  <div className="h-3 w-3 rounded-full bg-red-500" />
                  <div className="h-3 w-3 rounded-full bg-yellow-500" />
                  <div className="h-3 w-3 rounded-full bg-green-500" />
                </div>
                <span className="ml-4 font-mono text-xs text-gray-400">solution.py</span>
              </div>
              <div className="min-h-[400px] flex-1">
                <Editor
                  height="100%"
                  defaultLanguage="python"
                  theme="vs-dark"
                  value={userCode}
                  onChange={(v) => setUserCode(v || "")}
                  options={{ fontSize: 14, minimap: { enabled: false }, automaticLayout: true }}
                />
              </div>
              {!evaluation && (
                <Button
                  onClick={() => void submitCode()}
                  disabled={loading}
                  className="absolute bottom-6 right-6 rounded-xl bg-green-600 text-white shadow-lg hover:bg-green-700"
                >
                  {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="mr-2 h-5 w-5" />}
                  Soumettre la réponse
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default QuizModule;
