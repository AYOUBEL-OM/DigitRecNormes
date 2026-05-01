/**
 * Affichage rapport oral (dashboard) : libellés prudents, extensible.
 * Les scores bruts restent disponibles côté API ; ici on contrôle uniquement l’UI.
 */

/** Si true : affiche en plus les valeurs numériques (stress / confiance) entre parenthèses. */
export const ENABLE_ADVANCED_METRICS = false;

export function oralReportParseScore(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

/** 0–30 faible, 30–60 modéré, 60–100 élevé (bornes hautes exclusives sauf plafond 100). */
export function stressDisplayLabel(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "non disponible";
  const s = Math.max(0, Math.min(100, score));
  if (s < 30) return "faible";
  if (s < 60) return "modéré";
  return "élevé";
}

/** 0–40 faible, 40–70 moyenne, 70–100 élevée */
export function confidenceDisplayLabel(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "non disponible";
  const s = Math.max(0, Math.min(100, score));
  if (s < 40) return "faible";
  if (s < 70) return "moyenne";
  return "élevée";
}

/** Libellé prudent : pas de « non » catégorique sur l’absence de signal. */
export function phoneSignalPhrase(phoneDetected: unknown): string {
  if (phoneDetected === true) return "détecté";
  return "non détecté";
}
