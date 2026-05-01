import { User } from "@supabase/supabase-js";

type NormalizedError = {
  code?: string;
  details?: string;
  hint?: string;
  message: string;
  status?: number;
};

type ServiceResult<T> = {
  data: T | null;
  error: NormalizedError | null;
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type CandidateRegistrationPayload = {
  cin: string;
  email: string;
  cvFile: File | null;
  firstName: string;
  lastName: string;
  level: string;
  password: string;
  profile: string;
  title: string;
};

type CompanyRegistrationPayload = {
  companyName: string;
  email: string;
  password: string;
};

type ResolvedProfile = {
  accountType: "candidate" | "company" | "unknown";
  authUser: User;
  displayName: string;
  profile: Record<string, unknown> | null;
  source: string | null;
};

function normalizeError(error: unknown): NormalizedError {
  if (typeof error === "string") return { message: error };

  if (error && typeof error === "object") {
    const issue = error as any;
    return {
      code: issue.code,
      details: issue.details,
      hint: issue.hint,
      message: issue.message || "Request failed.",
      status: issue.status,
    };
  }

  return { message: "Request failed." };
}

async function run<T>(task: () => Promise<T>): Promise<ServiceResult<T>> {
  try {
    const data = await task();
    return { data, error: null };
  } catch (error) {
    return { data: null, error: normalizeError(error) };
  }
}

export type AuthAccountType = "entreprise" | "candidat";

/** Token d’accès entretien oral (`tests_oraux.candidate_access_token`). */
export const ORAL_INTERVIEW_TOKEN_KEY = "digitrec_oral_candidate_token";

/** En-tête HTTP : jeton de session oral (le JWT candidat reste dans `Authorization`). */
export const ORAL_SESSION_HEADER = "X-Digitrec-Oral-Token";

const ORAL_PENDING_TOKEN_KEY = "digitrec_oral_pending_token";

export function getPendingOralTokenFromSession(): string | null {
  try {
    const t = sessionStorage.getItem(ORAL_PENDING_TOKEN_KEY);
    return t?.trim() || null;
  } catch {
    return null;
  }
}

export function setPendingOralTokenInSession(token: string): void {
  const t = String(token || "").trim();
  if (!t) return;
  try {
    sessionStorage.setItem(ORAL_PENDING_TOKEN_KEY, t);
  } catch {
    /* ignore */
  }
}

export function clearPendingOralTokenFromSession(): void {
  try {
    sessionStorage.removeItem(ORAL_PENDING_TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function getOralInterviewAccessToken(): string | null {
  try {
    const t = localStorage.getItem(ORAL_INTERVIEW_TOKEN_KEY);
    return t?.trim() || null;
  } catch {
    return null;
  }
}

export function setOralInterviewAccessToken(token: string): void {
  const t = String(token || "").trim();
  if (!t) return;
  localStorage.setItem(ORAL_INTERVIEW_TOKEN_KEY, t);
  window.dispatchEvent(new Event("digitrec:oral-session-update"));
}

export function clearOralInterviewAccessToken(): void {
  try {
    localStorage.removeItem(ORAL_INTERVIEW_TOKEN_KEY);
    window.dispatchEvent(new Event("digitrec:oral-session-update"));
  } catch {
    /* ignore */
  }
}

const AUTH_STORAGE = {
  entreprise: {
    tokenKey: "entreprise_access_token",
    userKey: "entreprise_user",
  },
  candidat: {
    tokenKey: "candidat_access_token",
    userKey: "candidat_user",
  },
  // Legacy (avant séparation candidat/entreprise)
  legacy: {
    tokenKey: "access_token",
    userKey: "user",
  },
} as const;

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function migrateLegacyAuthStorageIfNeeded(): void {
  try {
    const legacyToken = localStorage.getItem(AUTH_STORAGE.legacy.tokenKey);
    const legacyUserRaw = localStorage.getItem(AUTH_STORAGE.legacy.userKey);
    if (!legacyToken || !legacyUserRaw?.trim()) return;

    const parsed = safeJsonParse(legacyUserRaw) as Record<string, unknown> | null;
    const type = parsed?.type;
    const target: AuthAccountType | null =
      type === "entreprise" ? "entreprise" : type === "candidat" ? "candidat" : null;
    if (!target) return;

    const tokKey = AUTH_STORAGE[target].tokenKey;
    const usrKey = AUTH_STORAGE[target].userKey;

    // Ne pas écraser une session déjà séparée
    if (!localStorage.getItem(tokKey)) localStorage.setItem(tokKey, legacyToken);
    if (!localStorage.getItem(usrKey)) localStorage.setItem(usrKey, legacyUserRaw);

    // Nettoyage legacy pour éviter collisions futures
    localStorage.removeItem(AUTH_STORAGE.legacy.tokenKey);
    localStorage.removeItem(AUTH_STORAGE.legacy.userKey);
  } catch {
    // ignore
  }
}

// Migration auto au chargement (sans casser les anciens logins)
migrateLegacyAuthStorageIfNeeded();

export function clearAuthStorage(type?: AuthAccountType) {
  if (type) {
    localStorage.removeItem(AUTH_STORAGE[type].tokenKey);
    localStorage.removeItem(AUTH_STORAGE[type].userKey);
    return;
  }
  // Full cleanup
  localStorage.removeItem(AUTH_STORAGE.entreprise.tokenKey);
  localStorage.removeItem(AUTH_STORAGE.entreprise.userKey);
  localStorage.removeItem(AUTH_STORAGE.candidat.tokenKey);
  localStorage.removeItem(AUTH_STORAGE.candidat.userKey);
  localStorage.removeItem(AUTH_STORAGE.legacy.tokenKey);
  localStorage.removeItem(AUTH_STORAGE.legacy.userKey);
}

export function getAccessToken(type: AuthAccountType): string | null {
  migrateLegacyAuthStorageIfNeeded();
  return localStorage.getItem(AUTH_STORAGE[type].tokenKey);
}

export function getStoredUser(type: AuthAccountType): Record<string, unknown> | null {
  migrateLegacyAuthStorageIfNeeded();
  const raw = localStorage.getItem(AUTH_STORAGE[type].userKey);
  if (!raw?.trim()) return null;
  const parsed = safeJsonParse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  return parsed as Record<string, unknown>;
}

export function setSession(type: AuthAccountType, accessToken: string, user: unknown): void {
  const token = String(accessToken || "").trim();
  if (!token) return;
  const userJson = JSON.stringify(user ?? {});
  localStorage.setItem(AUTH_STORAGE[type].tokenKey, token);
  localStorage.setItem(AUTH_STORAGE[type].userKey, userJson);
  window.dispatchEvent(new Event("digitrec:session-update"));
}

export function getSession(type: AuthAccountType) {
  return run(async () => {
    migrateLegacyAuthStorageIfNeeded();
    const token = localStorage.getItem(AUTH_STORAGE[type].tokenKey);
    const userJson = localStorage.getItem(AUTH_STORAGE[type].userKey);
    if (!token || !userJson?.trim()) {
      return null;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(userJson);
    } catch {
      clearAuthStorage(type);
      return null;
    }

    if (
      parsed === null ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      clearAuthStorage(type);
      return null;
    }

    return {
      access_token: token,
      user: parsed as Record<string, unknown>,
    };
  });
}

/**
 * Base API sans slash final. Définir `VITE_API_BASE_URL` en déploiement (ex. `https://api.example.com`
 * ou chaîne vide si l’API est servie sur le même origine que le frontend).
 * En développement local sans variable : repli sur le port FastAPI habituel.
 */
function resolveApiBaseUrl(): string {
  const raw = (import.meta.env as Record<string, string | undefined>).VITE_API_BASE_URL;
  if (raw !== undefined && String(raw).trim() !== "") {
    return String(raw).replace(/\/$/, "");
  }
  return "http://localhost:8000";
}

const API_BASE_URL = resolveApiBaseUrl();

/** Base API sans slash final. */
export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

/**
 * Rend une URL utilisable dans le navigateur : les chemins relatifs (/uploads/...)
 * pointent vers l’API FastAPI, pas vers le serveur Vite (sinon 404 SPA).
 */
export function resolveApiAssetUrl(href: string | null | undefined): string | null {
  if (!href?.trim()) return null;
  const u = href.trim();
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  const base = getApiBaseUrl();
  const path = u.startsWith("/") ? u : `/${u}`;
  return `${base}${path}`;
}

type ApiFetchAuthMode = AuthAccountType | "auto" | "none" | "oral";
type ApiFetchOptions = RequestInit & { auth?: ApiFetchAuthMode; oralTokenOverride?: string | null };

function inferAuthModeFromEndpoint(endpoint: string): ApiFetchAuthMode {
  // Auth endpoints: jamais de Bearer
  if (endpoint.startsWith("/api/auth/")) return "none";
  // Public quiz / offres publiques : pas de token d’app
  if (endpoint.startsWith("/api/offres/public/")) return "none";

  // Rapports oral dashboard entreprise (JWT entreprise uniquement)
  if (
    endpoint.startsWith("/api/oral/results/") ||
    endpoint.startsWith("/api/oral/debug/")
  ) {
    return "entreprise";
  }

  // Entretien oral candidat (token session oral, pas le JWT app)
  if (endpoint.startsWith("/api/oral/")) {
    return "oral";
  }

  // Espace entreprise
  if (
    endpoint.startsWith("/api/entreprises/") ||
    endpoint.startsWith("/api/offres") ||
    endpoint.startsWith("/api/quiz/results/") // reporting interne (si protégé)
  ) {
    return "entreprise";
  }

  // Espace candidat
  if (
    endpoint.startsWith("/api/candidatures/") ||
    endpoint.startsWith("/api/candidats/") ||
    endpoint.startsWith("/api/auth/candidat/")
  ) {
    return "candidat";
  }

  return "auto";
}

export async function apiFetch(endpoint: string, options: ApiFetchOptions = {}) {
  const authMode = options.auth ?? inferAuthModeFromEndpoint(endpoint);
  const oralOverride = options.oralTokenOverride?.trim() || null;
  const token =
    authMode === "none"
      ? null
      : authMode === "oral"
        ? getAccessToken("candidat")
        : authMode === "entreprise"
          ? getAccessToken("entreprise")
          : authMode === "candidat"
            ? getAccessToken("candidat")
            : // auto: privilégie entreprise si présent (routes dashboard), sinon candidat
              getAccessToken("entreprise") ?? getAccessToken("candidat");
  const oralHeaderToken =
    authMode === "oral"
      ? oralOverride || getOralInterviewAccessToken()?.trim() || null
      : null;
  const isFormData = options.body instanceof FormData;
  const method = String(options.method || "GET").toUpperCase();

  const baseHeaders: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(oralHeaderToken ? { [ORAL_SESSION_HEADER]: oralHeaderToken } : {}),
  };
  // Ne pas forcer Content-Type sur GET/HEAD sans body : évite certains preflights / CORS “Failed to fetch”.
  if (!isFormData && options.body != null && method !== "GET" && method !== "HEAD") {
    baseHeaders["Content-Type"] = "application/json";
  }
  const headers: Record<string, string> = {
    ...baseHeaders,
    ...((options.headers as Record<string, string>) ?? {}),
  };

  const url = `${API_BASE_URL}${endpoint}`;
  if (import.meta.env.DEV) {
    const isReport = endpoint.startsWith("/api/oral/results/");
    if (isReport) {
      console.log("FETCH REPORT URL:", url);
      console.log("FETCH REPORT HEADERS:", {
        hasAuthorization: Boolean(headers.Authorization),
        hasOralToken: Boolean(headers[ORAL_SESSION_HEADER]),
      });
      if (window.location.protocol === "https:" && url.startsWith("http://")) {
        console.warn(
          "[FETCH] Mixed-content risk: page is https but API is http",
          { page: window.location.href, api: url },
        );
      }
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      // ne pas passer `auth` à fetch
      headers,
    });
    if (import.meta.env.DEV && endpoint.startsWith("/api/oral/results/")) {
      console.log("FETCH REPORT RESPONSE:", {
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        contentType: response.headers.get("content-type"),
      });
    }
  } catch (err) {
    console.error("FETCH ERROR:", err);
    throw err;
  }

  if (!response.ok) {
    const text = await response.text();
    let message = text || "API error";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (parsed.detail !== undefined) {
        message =
          typeof parsed.detail === "string"
            ? parsed.detail
            : Array.isArray(parsed.detail)
              ? parsed.detail
                  .map((d: { msg?: string }) => d?.msg || String(d))
                  .join(", ")
              : typeof parsed.detail === "object" &&
                  parsed.detail !== null &&
                  "message" in parsed.detail &&
                  typeof (parsed.detail as { message?: unknown }).message === "string"
                ? String((parsed.detail as { message: string }).message)
                : JSON.stringify(parsed.detail);
      }
    } catch {
      /* keep raw text */
    }
    throw new ApiError(message, response.status);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

//
// 🔥 LOGIN FIX (ROLE-BASED)
//
export function signInWithPassword(
  email: string,
  password: string,
  userType: "candidat" | "entreprise"
) {
  return run(async () => {
    if (!userType) {
      throw new Error("Type de compte requis: candidat ou entreprise.");
    }

    const path =
      userType === "candidat"
        ? "/api/auth/candidat/login"
        : "/api/auth/entreprise/login";

    const payload =
      userType === "candidat"
        ? { email, mot_de_passe: password }
        : { email_prof: email, mot_de_passe: password };

    // Connexion « propre » : nettoie les deux sessions et l'ancien legacy pour éviter collisions.
    clearAuthStorage();

    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
      credentials: "omit",
    });

    if (!res.ok) {
      const text = await res.text();
      let message = "Email ou mot de passe incorrect";
      try {
        const parsed = JSON.parse(text) as { detail?: unknown };
        if (typeof parsed.detail === "string") {
          message = parsed.detail;
        } else if (Array.isArray(parsed.detail)) {
          message = parsed.detail
            .map((d: { msg?: string }) => d?.msg || String(d))
            .join(", ");
        }
      } catch {
        if (text) message = text;
      }
      throw new Error(message);
    }

    const data = await res.json();
    setSession(userType === "entreprise" ? "entreprise" : "candidat", data.access_token, data.user);

    return data;
  });
}

/**
 * Connexion candidat pour l’entretien oral : enregistre uniquement la session candidat
 * (ne vide pas forcément la session entreprise déjà présente sur le poste).
 */
export async function loginCandidatForOral(email: string, motDePasse: string) {
  const res = await fetch(`${API_BASE_URL}/api/auth/candidat/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ email: email.trim(), mot_de_passe: motDePasse }),
    cache: "no-store",
    credentials: "omit",
  });

  if (!res.ok) {
    const text = await res.text();
    let message = "Email ou mot de passe incorrect.";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") {
        message = parsed.detail;
      } else if (Array.isArray(parsed.detail)) {
        message = parsed.detail
          .map((d: { msg?: string }) => d?.msg || String(d))
          .join(", ");
      }
    } catch {
      if (text) message = text;
    }
    throw new Error(message);
  }

  const data = (await res.json()) as {
    access_token: string;
    user?: unknown;
  };
  setSession("candidat", data.access_token, data.user ?? {});
  return data;
}

export function signOut() {
  return run(async () => {
    clearAuthStorage();
    return true;
  });
}

export function registerCandidate(payload: CandidateRegistrationPayload) {
  return run(async () => {
    const form = new FormData();
    form.append("email", payload.email.trim());
    form.append("nom", payload.lastName.trim());
    form.append("prenom", payload.firstName.trim());
    form.append("mot_de_passe", payload.password);
    form.append("cin", payload.cin.trim());
    form.append("title", payload.title.trim());
    form.append("profile", payload.profile.trim());
    form.append("level", payload.level.trim());
    if (payload.cvFile) {
      form.append("cv", payload.cvFile);
    }

    const response = await fetch(
      `${API_BASE_URL}/api/auth/candidat/inscription`,
      {
        method: "POST",
        body: form,
      }
    );

    if (!response.ok) throw new Error(await response.text());

    return response.json();
  });
}

export function registerCompany(payload: CompanyRegistrationPayload) {
  return run(async () => {
    const response = await fetch(
      `${API_BASE_URL}/api/auth/entreprise/inscription`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_prof: payload.email,
          nom: payload.companyName,
          mot_de_passe: payload.password,
        }),
      }
    );

    if (!response.ok) throw new Error(await response.text());

    return response.json();
  });
}

export async function requestEntreprisePasswordReset(email: string): Promise<{ message: string }> {
  return apiFetch("/api/auth/entreprise/forgot-password", {
    method: "POST",
    auth: "none",
    body: JSON.stringify({ email }),
  }) as Promise<{ message: string }>;
}

export async function resetEntreprisePassword(
  token: string,
  newPassword: string
): Promise<{ message: string }> {
  return apiFetch("/api/auth/entreprise/reset-password", {
    method: "POST",
    auth: "none",
    body: JSON.stringify({ token, new_password: newPassword }),
  }) as Promise<{ message: string }>;
}

export type EntrepriseCandidatureItem = {
  id: string;
  offre_id: string;
  candidat_nom: string;
  offre_titre: string | null;
  statut: string;
  /** Note CV normalisée affichage liste historique (0–5). */
  score_ia: number | null;
  /** Moyenne des scores disponibles (CV %, écrit, oral si éligible et noté), 0–100. */
  score_final_pct?: number | null;
  /** Synthèse affichage : acceptee | a_revoir | refusee (sans écraser la base). */
  statut_synthese?: string | null;
};

export type OffreEntrepriseItem = {
  id: string;
  title: string | null;
  status: string | null;
  /** Présent sur la liste détaillée des offres entreprise */
  token_liens?: string | null;
  lien_candidature?: string | null;
  created_at?: string | null;
  lien_public_actif?: boolean;
  /** active | inactive | expirée */
  affichage_statut?: string | null;
};

export type CandidatureDetailsResponse = {
  candidate: {
    nom: string;
    prenom: string;
    email: string;
    cin: string | null;
    cv_url: string | null;
  };
  scores: {
    score_cv_matching: number | null;
    score_ecrit: number | null;
    score_oral: number | null;
    /** Moyenne des évaluations disponibles (même règle que la liste). */
    score_final_percent?: number | null;
  };
  status: {
    statut: string;
    etape_actuelle: string | null;
    statut_synthese?: string | null;
  };
  offre_titre: string | null;
};

export function getCandidatures() {
  return run(async () => {
    const data = await apiFetch("/api/entreprises/me/candidatures");
    return data as EntrepriseCandidatureItem[];
  });
}

export function getOffresEntreprise() {
  return run(async () => {
    const data = await apiFetch("/api/offres");
    return data as OffreEntrepriseItem[];
  });
}

export function getCandidatureDetails(candidatureId: string) {
  return run(async () => {
    const data = await apiFetch(
      `/api/entreprises/me/candidatures/${encodeURIComponent(candidatureId)}/details`,
    );
    return data as CandidatureDetailsResponse;
  });
}

export async function sendCandidateEmail(payload: {
  candidature_id: string;
  to: string;
  subject: string;
  message: string;
}): Promise<{ message: string; to: string }> {
  return apiFetch("/api/entreprises/me/send-candidate-email", {
    method: "POST",
    body: JSON.stringify(payload),
  }) as Promise<{ message: string; to: string }>;
}

export type DashboardRecrutementItem = {
  title: string;
  count_candidats: number;
  progression: number;
  stage: string;
};

export type DashboardStatsResponse = {
  nom_entreprise: string;
  total_candidats: number;
  offres_actives: number;
  entretiens_prevus: number;
  taux_conversion: number;
  recrutements_en_cours: DashboardRecrutementItem[];
};

export function getDashboardStats() {
  return run(async () => {
    const data = await apiFetch("/api/entreprises/me/dashboard-stats");
    return data as DashboardStatsResponse;
  });
}

export type EnterpriseProfile = {
  id: string;
  nom: string;
  email_prof: string;
  description: string | null;
};

/** Met à jour le JSON `user` en localStorage après un PATCH profil (même onglet). */
export function mergeStoredEnterpriseUser(profile: EnterpriseProfile): void {
  const raw = localStorage.getItem(AUTH_STORAGE.entreprise.userKey);
  if (!raw?.trim()) return;
  let u: Record<string, unknown>;
  try {
    u = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return;
  }
  if (u.type !== "entreprise") return;
  u.nom = profile.nom;
  u.email = profile.email_prof;
  u.email_prof = profile.email_prof;
  u.description = profile.description;
  localStorage.setItem(AUTH_STORAGE.entreprise.userKey, JSON.stringify(u));
  window.dispatchEvent(new Event("digitrec:session-update"));
}

export function getEnterpriseProfile() {
  return run(async () => {
    const data = await apiFetch("/api/entreprises/me");
    return data as EnterpriseProfile;
  });
}

export function updateProfile(payload: { nom?: string; description?: string | null }) {
  return run(async () => {
    const data = await apiFetch("/api/entreprises/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    return data as EnterpriseProfile;
  });
}

export function changePassword(ancienMotDePasse: string, nouveauMotDePasse: string) {
  return run(async () => {
    return apiFetch("/api/entreprises/me/change-password", {
      method: "POST",
      body: JSON.stringify({
        ancien_mot_de_passe: ancienMotDePasse,
        nouveau_mot_de_passe: nouveauMotDePasse,
      }),
    });
  });
}