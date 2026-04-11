import axios from "axios";

// Verifi had l-valeur darori
const baseURL = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";

export const api = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
});

const QUIZ_SESSION_KEY = "quiz_session_token";

api.interceptors.request.use((config) => {
  const token =
    (typeof sessionStorage !== "undefined" && sessionStorage.getItem(QUIZ_SESSION_KEY)) ||
    localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export { QUIZ_SESSION_KEY };