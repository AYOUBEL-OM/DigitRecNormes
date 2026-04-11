import axios from "axios";

// Verifi had l-valeur darori
const baseURL = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";

export const api = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  
  // N-zido check: ila kante l-request jaya mn l-quiz, ma-nsiftouch l-token darori
  // awla n-khlliw l-backend hwa li y-decidi.
  if (token && !config.url?.includes('/quiz/')) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});