/**
 * Timing strict entretien oral (aligné avec le backend `app.constants.oral_timing`).
 */

export const ORAL_PREP_TIME = 7;

export const ORAL_ANSWER_TIME_DEFAULT = 60;

export const ORAL_ANSWER_MARGIN_SECONDS = 5;

/** Tolérance réseau / encodage côté serveur */
export const ORAL_DURATION_REJECT_MARGIN = ORAL_ANSWER_MARGIN_SECONDS;

export const QUESTION_TIME_MAP = {
  intro: 45,
  normal: 60,
  advanced: 75,
} as const;

/** Seuil visuel : derniers 10 s */
export const ANSWER_WARN_LAST_SECONDS = 10;
/** Seuil visuel : derniers 5 s (rouge) */
export const ANSWER_CRITICAL_LAST_SECONDS = 5;

/** Aligné sur `backend/app/constants/oral_timing.py` (mêmes sous-chaînes). */
const ADVANCED_SNIPPETS = [
  "stratég",
  "strateg",
  "architecture",
  "due diligence",
  "restructuration",
  "transformation majeure",
  "m&a",
  "maîtrise",
  "pilotage",
  "vision",
] as const;

/**
 * Les 3 premières questions correspondent aux questions fixes d’introduction (banque orale).
 */
export function getAnswerSecondsForQuestion(questionText: string, questionIndexZeroBased: number): number {
  if (questionIndexZeroBased < 3) {
    return QUESTION_TIME_MAP.intro;
  }
  const t = (questionText || "").toLowerCase();
  if (ADVANCED_SNIPPETS.some((x) => t.includes(x))) {
    return QUESTION_TIME_MAP.advanced;
  }
  return QUESTION_TIME_MAP.normal;
}

export function getMaxAllowedClientSeconds(allowedAnswerSeconds: number): number {
  return allowedAnswerSeconds + ORAL_ANSWER_MARGIN_SECONDS;
}
