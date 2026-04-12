import axios from "axios";

// Verifi had l-valeur darori
const baseURL = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";

export const api = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const url = config.url ?? "";

  // Soumission du test : identité portée par le corps (id_candidature), pas le JWT app
  if (url.includes("/quiz/submit-test-result")) {
    return config;
  }

  const localToken = localStorage.getItem("access_token");

  const isQuizPublic =
    url.includes("/quiz/") && !url.includes("/quiz/submit-test-result");
  const isAuthAnonymous =
    /\/api\/auth\/[^/]+\/(login|inscription)/.test(url) ||
    url.includes("/api/auth/candidat/inscription");

  if (localToken && !isQuizPublic && !isAuthAnonymous) {
    config.headers.Authorization = `Bearer ${localToken}`;
  }
  return config;
});