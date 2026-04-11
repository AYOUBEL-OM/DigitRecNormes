import { CheckCircle2, Circle } from "lucide-react";

import { cn } from "@/lib/utils";

import type { Question } from "./types";

type QuizCardProps = {
  q: Question;
  index: number;
  /** Réponse choisie pour cette question (clé = index global) — requis pour la pagination. */
  selectedAnswer?: string | null;
  onSelect: (questionIndex: number, selectedValue: string) => void;
};

export function QuizCard({ q, index, selectedAnswer = null, onSelect }: QuizCardProps) {
  if (!q?.options?.length) {
    return null;
  }

  const selected = selectedAnswer;

  const handleSelect = (option: string) => {
    onSelect(index, option);
  };

  return (
    <div
      className={cn(
        "mb-6 rounded-2xl border border-border bg-card p-6 shadow-sm transition-shadow",
        "hover:shadow-md",
      )}
    >
      <div className="mb-6 flex gap-4">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold text-primary-foreground",
            "bg-primary shadow-md",
          )}
        >
          {index + 1}
        </span>
        <h3 className="pt-1 text-lg font-semibold leading-snug text-card-foreground">{q.question}</h3>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {q.options.map((option, i) => (
          <button
            key={i}
            type="button"
            onClick={() => handleSelect(option)}
            className={cn(
              "flex items-center justify-between rounded-xl border-2 p-4 text-left text-sm font-medium transition-colors",
              selected === option
                ? "border-primary bg-primary/10 text-primary"
                : "border-transparent bg-muted/60 text-muted-foreground hover:border-primary/30",
            )}
          >
            <span>{option}</span>
            {selected === option ? (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-primary" />
            ) : (
              <Circle className="h-5 w-5 shrink-0 text-muted-foreground/50" />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
