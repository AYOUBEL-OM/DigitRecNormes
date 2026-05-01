import axios from "axios";

const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
const baseURL =
  raw !== undefined && raw !== "" ? raw.replace(/\/$/, "") : "http://localhost:8000";

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

  // Priorité : routes entreprise utilisent le token entreprise, sinon token candidat.
  const entrepriseToken = localStorage.getItem("entreprise_access_token");
  const candidatToken = localStorage.getItem("candidat_access_token");

  const isQuizPublic =
    url.includes("/quiz/") &&
    !url.includes("/quiz/submit-test-result") &&
    !url.includes("/quiz/results/");
  const isAuthAnonymous =
    /\/api\/auth\/[^/]+\/(login|inscription)/.test(url) ||
    url.includes("/api/auth/candidat/inscription");

  const isOralEnterprise =
    url.includes("/api/oral/results/") || url.includes("/api/oral/debug/");
  const isOralCandidate = url.includes("/api/oral/") && !isOralEnterprise;
  const oralCandidateToken = localStorage.getItem("digitrec_oral_candidate_token")?.trim();

  const isSubscriptionsPublic = url.includes("/api/subscriptions/plans");
  const isStripeWebhook = url.includes("/api/subscriptions/webhook");

  const needsEntreprise =
    !isSubscriptionsPublic &&
    !isStripeWebhook &&
    (url.includes("/api/offres") ||
      url.includes("/api/entreprises/") ||
      url.includes("/api/subscriptions/") ||
      isOralEnterprise);

  const tokenToUse = isOralCandidate
    ? candidatToken || null
    : needsEntreprise
      ? entrepriseToken
      : candidatToken ?? entrepriseToken;

  if (tokenToUse && !isQuizPublic && !isAuthAnonymous) {
    config.headers.Authorization = `Bearer ${tokenToUse}`;
  }
  if (isOralCandidate && oralCandidateToken && config.headers) {
    (config.headers as Record<string, string>)["X-Digitrec-Oral-Token"] = oralCandidateToken;
  }
  return config;
});