/** Niveaux d'expérience attendus par l'API (`level` sur les offres). */
export const OFFER_EXPERIENCE_LEVELS = ["Junior", "Confirmé", "Senior"] as const;

export type OfferExperienceLevel = (typeof OFFER_EXPERIENCE_LEVELS)[number];

/** Préremplit la combobox à partir d'une valeur stockée (exacte ou texte libre ancien). */
export function normalizeStoredLevel(raw: string | null | undefined): string {
  if (raw == null) return "";
  const t = raw.trim();
  if (!t) return "";

  const exact = (OFFER_EXPERIENCE_LEVELS as readonly string[]).find((x) => x === t);
  if (exact) return exact;

  const ci = (OFFER_EXPERIENCE_LEVELS as readonly string[]).find(
    (x) => x.localeCompare(t, "fr", { sensitivity: "accent" }) === 0,
  );
  if (ci) return ci;

  const low = t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");

  if (/\bjunior\b/.test(low) || low === "jr") return "Junior";
  if (/\bsenior\b/.test(low) || low === "sr") return "Senior";
  if (/\bconfirme\b/.test(low) || /\bconfirm\w*\b/.test(low) || /\bintermediaire\b/.test(low)) {
    return "Confirmé";
  }

  return "";
}

export function isValidOfferExperienceLevel(value: string): value is OfferExperienceLevel {
  return (OFFER_EXPERIENCE_LEVELS as readonly string[]).includes(value);
}
