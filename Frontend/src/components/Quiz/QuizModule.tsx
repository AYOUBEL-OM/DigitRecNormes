import { useCallback, useEffect, useMemo, useState } from "react";
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
  Trophy,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/services/axios";

import { QuizCard } from "./QuizCard";
import type { Question } from "./types";

export type QuizModuleProps = {
  /** Identifiant UUID de l’offre ; sinon lu depuis l’URL (`offreId` ou `id`). */
  offreId?: string;
};

type QuizKind = "qcm" | "exercice";

const QUESTIONS_PER_PAGE = 5;

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

function normalizeQuizType(payload: any): QuizKind | null {
  const t = payload.quiz_type;
  if (t === "qcm" || t === "exercice") return t;
  
  // التحقق من EXERCICE إذا كان موجوداً في الـ payload
  if (payload.EXERCICE || (payload.title != null && payload.description != null)) {
    return "exercice";
  }
  if (Array.isArray(payload.questions)) {
    return "qcm";
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
    api.get<QuizConfigResponse>(`/api/quiz/config/${oid}`)
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

    return () => { cancelled = true; };
  }, [offreId]);

  const applyGeneratePayload = useCallback((payload: any) => {
    const kind = normalizeQuizType(payload);
    if (!kind) {
      setError("Réponse serveur : type de quiz non reconnu.");
      setActiveKind(null);
      return;
    }

    setActiveKind(kind);
    setError(null);

    if (kind === "qcm") {
      setExercice(null);
      setUserCode("");
      setQuestions(Array.isArray(payload.questions) ? payload.questions : []);
    } else {
      setQuestions([]);
      const exData = payload.EXERCICE || payload;
      setExercice({
        title: exData.title || "Exercice technique",
        description: exData.description || "",
        initial_code: exData.initial_code || "",
      });
      setUserCode(exData.initial_code || "");
    }
  }, []);

  const handleGenerate = async () => {
    if (!offreId || verifyState !== "ok") return;

    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(`/api/generate/${offreId}`);
      const payload = typeof data === "string" ? JSON.parse(data) : data;
      applyGeneratePayload(payload);
    } catch (e) {
      setError("Erreur de génération. Vérifiez la connexion au backend.");
    } finally {
      setLoading(false);
    }
  };

  const calculateQcmScore = () => {
    let correct = 0;
    questions.forEach((q, idx) => {
      if (userAnswers[idx] === q.answer) correct++;
    });
    const finalScore = questions.length ? Math.round((correct / questions.length) * 100) : 0;
    setScore(finalScore);
    if (finalScore >= 70) confetti();
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
      if (result.score >= 70) confetti();
    } catch {
      setError("Erreur lors de l’évaluation.");
    } finally {
      setLoading(false);
    }
  };

  // Logic pour l'affichage (Pagination, etc.)
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
          <h1 className="text-3xl font-bold md:text-4xl">Digit<span className="text-primary">REC</span> — Test écrit</h1>
          {activeKind && (
             <Badge variant="secondary" className="mt-4 uppercase">Test en cours — {activeKind}</Badge>
          )}
        </div>

        {verifyState === "ok" && !activeKind && (
          <div className="mx-auto mb-8 max-w-2xl rounded-xl border bg-card p-6 shadow-sm">
            <h2 className="text-lg font-semibold">{offreConfig?.title || "Offre validée"}</h2>
            <p className="text-sm text-muted-foreground mt-1">{offreConfig?.profile} | {offreConfig?.level}</p>
            <Button onClick={handleGenerate} disabled={loading} className="mt-6 w-full rounded-xl">
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Commencer le test
            </Button>
          </div>
        )}

        {error && (
          <div className="mx-auto mb-6 flex max-w-3xl items-center gap-3 rounded-xl bg-destructive/10 p-4 text-destructive border border-destructive/20">
            <AlertCircle className="h-5 w-5" />
            <span className="text-sm font-medium">{error}</span>
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
                onSelect={(idx, val) => setUserAnswers(p => ({...p, [idx]: val}))}
              />
            ))}
            <div className="flex flex-col items-center gap-6 mt-8">
              <div className="flex items-center gap-4">
                <Button variant="outline" disabled={currentPage === 0} onClick={() => setCurrentPage(p => p - 1)}>
                  <ChevronLeft className="h-4 w-4 mr-1" /> Précédent
                </Button>
                <span className="text-sm text-muted-foreground">Page {currentPage + 1} / {totalQcmPages}</span>
                <Button variant="outline" disabled={currentPage >= totalQcmPages - 1} onClick={() => setCurrentPage(p => p + 1)}>
                  Suivant <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
              <Button 
                size="lg" 
                className="bg-green-600 hover:bg-green-700 text-white px-12 rounded-2xl"
                disabled={Object.keys(userAnswers).length < questions.length}
                onClick={calculateQcmScore}
              >
                Terminer le test
              </Button>
            </div>
          </div>
        )}

        {/* --- SECTION RESULTAT --- */}
        {score !== null && (
          <div className="mx-auto max-w-md rounded-3xl border-4 border-primary bg-card p-10 text-center shadow-2xl">
            <Trophy className="mx-auto mb-4 h-16 w-16 text-yellow-500" />
            <h2 className="text-2xl font-bold">Votre Score</h2>
            <div className="my-4 text-7xl font-black text-primary">{score}%</div>
            <Button variant="ghost" className="mt-4 gap-2" onClick={() => window.location.reload()}>
              <RotateCcw className="h-4 w-4" /> Recommencer
            </Button>
          </div>
        )}

        {/* --- SECTION EXERCICE --- */}
        {activeKind === "exercice" && exercice && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 min-h-[500px]">
            <div className="rounded-xl border bg-card p-8 shadow-sm overflow-y-auto">
              <Badge className="mb-4">EXERCICE</Badge>
              <h2 className="text-2xl font-bold mb-4">{exercice.title}</h2>
              <div className="prose prose-sm dark:prose-invert text-muted-foreground whitespace-pre-wrap">
                {exercice.description}
              </div>
              {evaluation && (
                <div className="mt-8 rounded-2xl bg-primary p-6 text-primary-foreground">
                  <div className="flex justify-between items-center mb-2">
                    <span className="font-bold">Score IA</span>
                    <span className="text-3xl font-black">{evaluation.score}%</span>
                  </div>
                  <p className="text-sm opacity-90">{evaluation.feedback}</p>
                </div>
              )}
            </div>

            <div className="flex flex-col rounded-xl border bg-[#1e1e1e] shadow-2xl overflow-hidden relative">
              <div className="bg-[#2d2d2d] px-4 py-2 border-b border-[#333] flex items-center gap-2">
                <div className="flex gap-1.5"><div className="w-3 h-3 rounded-full bg-red-500"/><div className="w-3 h-3 rounded-full bg-yellow-500"/><div className="w-3 h-3 rounded-full bg-green-500"/></div>
                <span className="text-xs text-gray-400 ml-4 font-mono">solution.py</span>
              </div>
              <div className="flex-1 min-h-[400px]">
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
                <Button onClick={submitCode} disabled={loading} className="absolute bottom-6 right-6 bg-green-600 hover:bg-green-700 text-white rounded-xl shadow-lg">
                  {loading ? <Loader2 className="animate-spin h-5 w-5" /> : <Send className="h-5 w-5 mr-2" />}
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