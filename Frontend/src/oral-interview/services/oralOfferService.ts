import { apiFetch } from "@/services/authService";

/** Contexte affichage : JWT candidat + en-tête `X-Digitrec-Oral-Token`. */
export type OralOffreSummary = {
  titre_poste: string;
  departement: string | null;
  nombre_questions_oral: number | null;
  /** Déjà enregistrée côté serveur (rechargement de page). */
  candidate_photo_uploaded?: boolean;
};

export function fetchOralBootstrap(opts?: { oralTokenOverride?: string | null }) {
  return apiFetch("/api/oral/bootstrap", {
    oralTokenOverride: opts?.oralTokenOverride ?? undefined,
  }) as Promise<OralOffreSummary>;
}
