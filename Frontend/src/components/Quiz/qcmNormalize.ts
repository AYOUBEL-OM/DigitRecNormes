/** Aligné sur ``backend/app/services/qcm_normalization.py`` (clé de comparaison QCM). */

const LETTER_ONLY = /^\s*([A-Za-z])\s*$/;
const PREFIX_LETTER = /^\s*([A-Za-z])\s*[\.\)]\s*(.+)$/s;

function stripDiacritics(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function collapseWs(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function stripOptionPrefix(s: string): string {
  const t = s.trim();
  const m = t.match(PREFIX_LETTER);
  if (m) return m[2].trim();
  return t;
}

export function normalizeQcmAnswer(value: unknown, options: string[]): string {
  const opts = (options ?? []).map(String);
  if (value == null || value === "") return "";
  if (typeof value === "boolean") return "";
  if (typeof value === "number" && Number.isFinite(value) && Number.isInteger(value)) {
    const iv = value as number;
    if (iv >= 0 && iv < opts.length) {
      return collapseWs(stripDiacritics(stripOptionPrefix(opts[iv]).toLowerCase()));
    }
    return collapseWs(stripDiacritics(String(value).toLowerCase()));
  }
  const s = String(value).trim();
  if (!s) return "";
  const letter = s.match(LETTER_ONLY);
  if (letter && opts.length) {
    const idx = letter[1].toUpperCase().charCodeAt(0) - 65;
    if (idx >= 0 && idx < opts.length) {
      return collapseWs(stripDiacritics(stripOptionPrefix(opts[idx]).toLowerCase()));
    }
  }
  if (/^\d+$/.test(s) && opts.length) {
    const idx = parseInt(s, 10);
    if (idx >= 0 && idx < opts.length) {
      return collapseWs(stripDiacritics(stripOptionPrefix(opts[idx]).toLowerCase()));
    }
  }
  return collapseWs(stripDiacritics(stripOptionPrefix(s).toLowerCase()));
}

export function qcmAnswersEquivalent(
  candidate: unknown,
  expected: unknown,
  options: string[],
): boolean {
  const ca = normalizeQcmAnswer(candidate, options);
  const ea = normalizeQcmAnswer(expected, options);
  if (!ca || !ea) return false;
  return ca === ea;
}
