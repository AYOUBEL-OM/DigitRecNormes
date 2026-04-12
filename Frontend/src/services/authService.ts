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

export function getSession() {
  return run(async () => {
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    return { access_token: token };
  });
}

const API_BASE_URL =
  (import.meta.env as Record<string, string | undefined>).VITE_API_BASE_URL ??
  "http://localhost:8000";

export async function apiFetch(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem("access_token");
  const isFormData = options.body instanceof FormData;

  const baseHeaders: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  if (!isFormData) {
    baseHeaders["Content-Type"] = "application/json";
  }
  const headers: Record<string, string> = {
    ...baseHeaders,
    ...((options.headers as Record<string, string>) ?? {}),
  };

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

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
              : JSON.stringify(parsed.detail);
      }
    } catch {
      /* keep raw text */
    }
    throw new Error(message);
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

    // Connexion « propre » : évite qu’un ancien JWT ne soit mélangé à la requête côté extensions / onglets.
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
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("user", JSON.stringify(data.user));

    return data;
  });
}

const AUTH_STORAGE_KEYS = ["access_token", "user"] as const;

export function clearAuthStorage() {
  for (const key of AUTH_STORAGE_KEYS) {
    localStorage.removeItem(key);
  }
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