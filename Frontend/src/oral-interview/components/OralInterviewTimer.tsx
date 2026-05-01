import { cn } from "@/lib/utils";
import {
  ANSWER_CRITICAL_LAST_SECONDS,
  ANSWER_WARN_LAST_SECONDS,
} from "@/oral-interview/constants/oralTiming";

export type OralTimerPhase = "prep" | "answer" | "idle";

type OralInterviewTimerProps = {
  phase: OralTimerPhase;
  prepSecondsLeft: number | null;
  answerSecondsLeft: number | null;
  allowedAnswerSeconds: number;
  className?: string;
};

function answerTone(seconds: number | null): "success" | "warning" | "destructive" {
  if (seconds == null) return "success";
  if (seconds <= ANSWER_CRITICAL_LAST_SECONDS) return "destructive";
  if (seconds <= ANSWER_WARN_LAST_SECONDS) return "warning";
  return "success";
}

export default function OralInterviewTimer({
  phase,
  prepSecondsLeft,
  answerSecondsLeft,
  allowedAnswerSeconds,
  className,
}: OralInterviewTimerProps) {
  const ansClasses = {
    success: "border-emerald-500/40 bg-emerald-500/15 text-emerald-950 dark:text-emerald-100",
    warning: "border-amber-500/50 bg-amber-500/15 text-amber-950 dark:text-amber-100",
    destructive: "border-destructive/50 bg-destructive/15 text-destructive",
  };

  const showPrep = phase === "prep" && prepSecondsLeft != null && prepSecondsLeft > 0;
  const showAnswer = phase === "answer" && answerSecondsLeft != null;

  if (phase === "idle" || (!showPrep && !showAnswer)) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex min-w-[220px] flex-col gap-2 rounded-xl border border-white/20 bg-black/10 px-4 py-3 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
    >
      {showPrep ? (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 font-semibold text-emerald-950 dark:text-emerald-100">
          <span className="text-emerald-900/80 dark:text-emerald-100/80">Temps de préparation : </span>
          <span className="tabular-nums">{prepSecondsLeft}s</span>
        </div>
      ) : null}
      {showAnswer ? (
        <div
          className={cn(
            "rounded-lg border px-3 py-2 font-semibold",
            ansClasses[answerTone(answerSecondsLeft)],
          )}
        >
          <span className="text-muted-foreground">Temps restant : </span>
          <span className="tabular-nums">{answerSecondsLeft}s</span>
          <span className="ml-2 text-xs font-normal opacity-80">/ {allowedAnswerSeconds}s</span>
        </div>
      ) : null}
    </div>
  );
}
