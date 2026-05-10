import { useCallback, useEffect, useRef, useState } from "react";
import {
  getAccessToken,
  getApiBaseUrl,
  getOralInterviewAccessToken,
  ORAL_SESSION_HEADER,
} from "@/services/authService";
import {
  bboxToNorm,
  createInitialGazeState,
  type GazeDirection,
  updateStableGaze,
} from "@/oral-interview/utils/gazeTracking";
import {
  computeFaceFrameMetrics,
  computePhonePostureCore,
  computePhonePostureScore,
  PHONE_POSTURE_REPORT_THRESHOLD,
  PHONE_POSTURE_SUSPICION_THRESHOLD,
} from "@/oral-interview/utils/phonePosture";
import {
  analyzeGazeWindow,
  computeWindowPhonePostureScore,
  pushGazeWindowSample,
  type GazeWindowSample,
} from "@/oral-interview/utils/gazeWindowAnalysis";

type FaceDetectorCtor = new (opts?: { maxDetectedFaces?: number; fastMode?: boolean }) => {
  detect: (source: HTMLVideoElement) => Promise<Array<{ boundingBox: DOMRectReadOnly }>>;
};

function getFaceDetectorCtor(): FaceDetectorCtor | null {
  const w = window as unknown as { FaceDetector?: FaceDetectorCtor };
  return w.FaceDetector ?? null;
}

/** Échantillonnage caméra local */
const GAZE_SAMPLE_INTERVAL_MS = 400;
/** Heartbeat réseau */
const PROCTORING_HEARTBEAT_INTERVAL_MS = 1200;

/** Cooldown global entre alertes UI proctoring (bruit réduit, détection backend inchangée). */
const ALERT_COOLDOWN_MS = 5000;

/** Alertes téléphone masquées côté UI (événements / scoring / rapport inchangés). */
const SILENCED_PHONE_WARNING_IDS = new Set(["phone", "phone_hb"]);

/** Présence : visage absent / vidéo non prête sur N heartbeats consécutifs avant anomalie (aligné backend ~6–8). */
const PRESENCE_ANOMALY_HEARTBEATS_REQUIRED = 6;
/** Entre deux envois `presence_anomaly` (anti micro-coupures / lag). */
const PRESENCE_ANOMALY_COOLDOWN_MS = 9000;
/** Téléphone : preuves strictes uniquement (posture + streak + regard bas). */
const PHONE_STRICT_COMBINED_MIN = 0.65;
const PHONE_STRICT_STREAK_MIN = 4;
const PHONE_STRICT_DOWN_RATIO_MIN = 0.7;
/** Échantillons gaze consécutifs (~400 ms) ou heartbeats cohérents avant événement réseau. */
const PHONE_STRICT_SAMPLE_TICKS = 3;
const PHONE_EVENT_COOLDOWN_MS = 14000;
/** Regard hors cadre : N heartbeats consécutifs avant anomalie « off_frame ». */
const OFF_FRAME_ANOMALY_HEARTBEATS_REQUIRED = 3;
/** Multi-visages : N heartbeats consécutifs avec faces_count ≥ 2 (aligné flush). */
const MULTI_FACE_HEARTBEATS_REQUIRED = 3;
const FACES_HISTORY_MAX = 5;
const MULTI_FACE_HISTORY_MAJORITY = 3;
/** ~3 heartbeats à 400 ms/échantillon. */
const MULTI_FACE_MIN_CONSECUTIVE_SAMPLES = 9;
const PROCTORING_VIDEO_WIDTH_MIN = 200;
const PROCTORING_WINDOW_RAPID_IGNORE = 0.6;
const PROCTORING_BRIGHTNESS_MIN = 0.11;
/** Avertissement onglet : au moins 2 passages document hidden dans cette fenêtre temporelle. */
const TAB_ALERT_WINDOW_MS = 10_000;
/** Regard hors centre : afficher l’alerte seulement après N heartbeats consécutifs. */
const GAZE_ALERT_MIN_CONSECUTIVE_HEARTBEATS = 4;

const GAZE_RATIO_SUSPICION_LOW = 0.38;
const GAZE_RATIO_SUSPICION_HIGH = 0.62;

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

function round3(x: number): number {
  return Math.round(x * 1000) / 1000;
}

function matrixYawPitchDeg(m: number[]): { yaw: number; pitch: number } | null {
  // Matrice 4x4 colonne-majeure (MediaPipe). On extrait la rotation et on approxime yaw/pitch.
  // Définitions : yaw = rotation autour de Y ; pitch = rotation autour de X.
  if (!Array.isArray(m) || m.length < 16) return null;
  const r00 = m[0];
  const r01 = m[4];
  const r02 = m[8];
  const r10 = m[1];
  const r11 = m[5];
  const r12 = m[9];
  const r20 = m[2];
  const r21 = m[6];
  const r22 = m[10];
  if (![r00, r01, r02, r10, r11, r12, r20, r21, r22].every((x) => Number.isFinite(x))) return null;

  // Convention type yaw-pitch-roll (Tait–Bryan, Y-X-Z) : on garde yaw/pitch uniquement.
  // yaw = atan2(r02, r22)
  // pitch = asin(-r12)  (limité)
  const yaw = Math.atan2(r02, r22);
  const pitch = Math.asin(Math.max(-1, Math.min(1, -r12)));
  return { yaw: (yaw * 180) / Math.PI, pitch: (pitch * 180) / Math.PI };
}

function meanPoint(pts: Array<{ x: number; y: number }>): { x: number; y: number } {
  if (!pts.length) return { x: 0.5, y: 0.5 };
  let sx = 0;
  let sy = 0;
  for (const p of pts) {
    sx += p.x;
    sy += p.y;
  }
  return { x: sx / pts.length, y: sy / pts.length };
}

/** Boîte visage en pixels vidéo (même convention que FaceDetector) à partir des landmarks MediaPipe normalisés. */
/** Luminance moyenne 0–1 sur un petit échantillon de la frame (détection peu fiable si trop sombre). */
function sampleVideoBrightness01(video: HTMLVideoElement): number | null {
  try {
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (w < 8 || h < 8) return null;
    const sw = Math.min(48, w);
    const sh = Math.min(48, h);
    const canvas = document.createElement("canvas");
    canvas.width = sw;
    canvas.height = sh;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, w, h, 0, 0, sw, sh);
    const data = ctx.getImageData(0, 0, sw, sh).data;
    let sum = 0;
    let n = 0;
    const step = 16;
    for (let i = 0; i < data.length; i += step) {
      sum += (data[i] + data[i + 1] + data[i + 2]) / (255 * 3);
      n += 1;
    }
    return n ? sum / n : null;
  } catch {
    return null;
  }
}

function landmarksToVideoBoundingBox(
  lm: Array<{ x: number; y: number }>,
  video: HTMLVideoElement,
): DOMRectReadOnly {
  const vw = Math.max(1, video.videoWidth || video.clientWidth || 1);
  const vh = Math.max(1, video.videoHeight || video.clientHeight || 1);
  let minX = 1;
  let minY = 1;
  let maxX = 0;
  let maxY = 0;
  for (const p of lm) {
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
  }
  const pad = 0.002 * Math.min(vw, vh);
  const left = minX * vw - pad;
  const top = minY * vh - pad;
  const width = Math.max(1, (maxX - minX) * vw + pad * 2);
  const height = Math.max(1, (maxY - minY) * vh + pad * 2);
  return new DOMRect(left, top, width, height);
}

function mpGazeFromLandmarks(
  lm: Array<{ x: number; y: number }>,
): { gaze_ratio?: number; gaze_direction: GazeDirection; quality: number } {
  // Indices FaceMesh (MediaPipe):
  // - Left eye: outer=33, inner=133, top=159, bottom=145, iris=468..472
  // - Right eye: outer=263, inner=362, top=386, bottom=374, iris=473..477
  const idx = {
    le_outer: 33,
    le_inner: 133,
    le_top: 159,
    le_bottom: 145,
    li0: 468,
    li1: 469,
    li2: 470,
    li3: 471,
    li4: 472,
    re_outer: 263,
    re_inner: 362,
    re_top: 386,
    re_bottom: 374,
    ri0: 473,
    ri1: 474,
    ri2: 475,
    ri3: 476,
    ri4: 477,
  } as const;
  const get = (i: number) => lm[i];
  const required = [
    idx.le_outer,
    idx.le_inner,
    idx.le_top,
    idx.le_bottom,
    idx.re_outer,
    idx.re_inner,
    idx.re_top,
    idx.re_bottom,
    idx.li0,
    idx.li4,
    idx.ri0,
    idx.ri4,
  ];
  for (const i of required) {
    const p = get(i);
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
      return { gaze_direction: "unknown", quality: 0.0 };
    }
  }

  const leftIris = meanPoint([get(idx.li0), get(idx.li1), get(idx.li2), get(idx.li3), get(idx.li4)]);
  const rightIris = meanPoint([get(idx.ri0), get(idx.ri1), get(idx.ri2), get(idx.ri3), get(idx.ri4)]);

  const leInner = get(idx.le_inner);
  const leOuter = get(idx.le_outer);
  const reInner = get(idx.re_inner);
  const reOuter = get(idx.re_outer);

  const leTop = get(idx.le_top);
  const leBottom = get(idx.le_bottom);
  const reTop = get(idx.re_top);
  const reBottom = get(idx.re_bottom);

  const leW = Math.abs(leOuter.x - leInner.x);
  const reW = Math.abs(reOuter.x - reInner.x);
  const leH = Math.abs(leBottom.y - leTop.y);
  const reH = Math.abs(reBottom.y - reTop.y);

  const minW = Math.min(leW, reW);
  const minH = Math.min(leH, reH);
  if (minW < 0.01 || minH < 0.01) {
    return { gaze_direction: "unknown", quality: 0.0 };
  }

  // Ratio horizontal normalisé [0..1] de l'iris dans l'œil (0=gauche, 1=droite) par œil.
  // Pour être cohérent entre les yeux, on définit le "gauche->droite" en utilisant inner/outer du même côté.
  const leftRatio = clamp01((leftIris.x - Math.min(leInner.x, leOuter.x)) / leW);
  const rightRatio = clamp01((rightIris.x - Math.min(reInner.x, reOuter.x)) / reW);
  const gaze_ratio = clamp01((leftRatio + rightRatio) / 2);

  // Ratio vertical [0..1] (0=haut,1=bas)
  const leftV = clamp01((leftIris.y - Math.min(leTop.y, leBottom.y)) / leH);
  const rightV = clamp01((rightIris.y - Math.min(reTop.y, reBottom.y)) / reH);
  const gaze_v = clamp01((leftV + rightV) / 2);

  // Qualité heuristique : pénalise yeux très "fermés" (faible hauteur) et ratios proches des bords extrêmes.
  const openness = clamp01(minH / 0.06);
  const edgePenalty = 1 - Math.min(1, Math.abs(gaze_ratio - 0.5) * 2.0);
  const quality = clamp01(openness * 0.7 + edgePenalty * 0.3);

  // Direction : priorité au fort signal vertical (haut/bas), puis horizontal.
  let gaze_direction: GazeDirection = "center";
  if (gaze_v <= 0.32) gaze_direction = "up";
  else if (gaze_v >= 0.68) gaze_direction = "down";
  else if (gaze_ratio < 0.42) gaze_direction = "left";
  else if (gaze_ratio > 0.58) gaze_direction = "right";

  return { gaze_ratio: round3(gaze_ratio), gaze_direction, quality: round3(quality) };
}

/** Message unique affiché pour les sorties d’onglet (aligné avec /proctoring-event). */
export const TAB_VISIBILITY_MESSAGE =
  "Merci de rester sur l’onglet de l’entretien. Les sorties d’onglet peuvent être signalées.";

const GAZE_DIRS = new Set(["center", "left", "right", "up", "down", "off", "unknown"]);

function normalizeGazeDirection(g: unknown): GazeDirection {
  const s = String(g ?? "")
    .trim()
    .toLowerCase();
  if (GAZE_DIRS.has(s)) return s as GazeDirection;
  return "unknown";
}

function buildProctoringHeartbeatPayload(raw: Record<string, unknown>): Record<string, unknown> {
  const gaze_direction = normalizeGazeDirection(
    raw.gaze_direction ?? raw.gaze_region ?? raw.gaze ?? "unknown",
  );
  const facesRaw = raw.faces_count;
  let facesNum =
    typeof facesRaw === "number" && !Number.isNaN(facesRaw) ? Math.trunc(facesRaw) : 0;
  if (facesNum < 0) facesNum = 0;
  const face_visible = Boolean(raw.face_visible);
  const face_detected =
    typeof raw.face_detected === "boolean" ? raw.face_detected : facesNum >= 1;
  const rapid = Boolean(raw.rapid_motion ?? raw.rapid_movement);
  let objects: unknown[] = Array.isArray(raw.objects) ? [...raw.objects] : [];
  objects = objects.map((o) => (typeof o === "string" ? o.toLowerCase().trim() : String(o))).filter(Boolean);
  const ts = typeof raw.timestamp === "number" ? raw.timestamp : Date.now();
  return {
    ...raw,
    timestamp: ts,
    gaze_direction,
    gaze_region: gaze_direction,
    faces_count: facesNum,
    face_visible,
    face_detected,
    rapid_motion: rapid,
    rapid_movement: rapid,
    objects,
    tab_switch: Boolean(raw.tab_switch),
    fullscreen_exit: Boolean(raw.fullscreen_exit),
  };
}

type ProctoringResponse = {
  status?: string;
  ok?: boolean;
  candidate_warning?: {
    id: string;
    message: string;
    severity?: string;
  };
};

async function postProctoring(
  accessToken: string,
  eventType: string,
  metadata: Record<string, unknown> = {},
): Promise<ProctoringResponse | null> {
  const oralTok = accessToken.trim() || getOralInterviewAccessToken()?.trim();
  const jwt = getAccessToken("candidat")?.trim();
  if (!oralTok) {
    console.warn("[PROCTORING] post skipped: missing oral session token", {
      event_type: eventType,
    });
    return null;
  }
  const base = getApiBaseUrl();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    [ORAL_SESSION_HEADER]: oralTok,
  };
  if (jwt) {
    headers.Authorization = `Bearer ${jwt}`;
  }
  const res = await fetch(`${base}/api/oral/proctoring-event`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      event_type: eventType,
      metadata,
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  try {
    return (await res.json()) as ProctoringResponse;
  } catch {
    return null;
  }
}

export type OralProctoringWarning = {
  id: string;
  message: string;
  severity: "info" | "warn";
};

type UseOralProctoringOpts = {
  accessToken: string | undefined;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  getVideoElement?: () => HTMLVideoElement | null;
  enabled: boolean;
};

/**
 * Tente de débloquer la lecture média (politique autoplay : muted obligatoire).
 */
function ensureVideoPlaybackAttempt(video: HTMLVideoElement): void {
  try {
    video.muted = true;
    video.defaultMuted = true;
    video.setAttribute("muted", "");
    video.setAttribute("playsinline", "true");
    video.setAttribute("webkit-playsinline", "true");
  } catch {
    /* ignore */
  }
  if (video.srcObject && video.readyState < 2) {
    void video.play().catch((e) => {
      console.warn("[PROCTORING] video.play() deferred", e);
    });
  }
}

export function useOralProctoring({
  accessToken,
  videoRef,
  getVideoElement,
  enabled,
}: UseOralProctoringOpts) {
  const [warnings, setWarnings] = useState<OralProctoringWarning[]>([]);
  const lastBbox = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const noFaceStreak = useRef(0);
  /** Épisode « présence manquante » : évite les envois répétés d’événements tant que l’état reste vrai. */
  const presenceAnomalyEpisodeActiveRef = useRef(false);
  const lastPresenceAnomalySentAtRef = useRef(0);
  const gazeOffAxisStreak = useRef(0);
  const phoneSuspicionStreak = useRef(0);
  const lastFaceCenterY = useRef<number | null>(null);
  const phoneDownStepStreak = useRef(0);
  const lastPhoneSuspectedSent = useRef(0);
  const lastOtherPersonSent = useRef(0);
  const sessionTokenRef = useRef<string | null>(null);
  const faceDetectorRef = useRef<{ detect: (v: HTMLVideoElement) => Promise<unknown> } | null>(null);
  const gazeStateRef = useRef(createInitialGazeState());
  const proctoringStateRef = useRef<Record<string, unknown>>({});
  const lastHeartbeatSentAtRef = useRef(0);
  /** Dernière <video> sur laquelle on a branché les listeners média */
  const videoListenersAttachedRef = useRef<HTMLVideoElement | null>(null);
  const videoListenerAbortRef = useRef<AbortController | null>(null);
  /** Fenêtre glissante pour ratios / qualité / suspicion (échantillons ~400 ms). */
  const gazeWindowBufferRef = useRef<GazeWindowSample[]>([]);
  const lastGazeWindowMetricsRef = useRef<ReturnType<typeof analyzeGazeWindow> | null>(null);
  /** Une fois téléphone détecté sur la session, reste vrai jusqu’à fin du proctoring (reset au cleanup). */
  const phoneDetectedLatchRef = useRef(false);
  const mpRef = useRef<{
    faceLandmarker: unknown;
    detectForVideo?: (video: HTMLVideoElement, nowMs: number) => any;
  } | null>(null);
  const mpInitOnceRef = useRef(false);
  const lastHeadMotionSentAtRef = useRef(0);
  const lastPhoneDetectedSentAtRef = useRef(0);
  /** Heartbeats consécutifs où `dominant_gaze_direction === "down"` (période ~1,2 s). */
  const phoneDownDominantHbStreakRef = useRef(0);
  const lastPhoneRawDebugLogAtRef = useRef(0);
  /** Frame stricte téléphone : confirmée sur plusieurs ticks / heartbeats. */
  const phoneStrictSampleStreakRef = useRef(0);
  const lastStrictPhoneFrameRef = useRef(false);
  const phoneStrictHeartbeatStreakRef = useRef(0);
  /** Dernière readyState <video> (pour preuve heartbeat). */
  const lastVideoReadyStateRef = useRef(0);
  /** Hystérésis présence : il faut 2 heartbeats « bons » pour effacer le compteur manquant. */
  const presenceGoodStreakRef = useRef(0);
  /** Heartbeats consécutifs : vidéo non prête ou visage non visible. */
  const presenceMissingHbCountRef = useRef(0);
  /** Heartbeats consécutifs avec faces_count ≥ 2 (payload). */
  const multiFaceHbStreakRef = useRef(0);
  /** Derniers faces_count « stables » (après filtre flou / mouvement). */
  const facesHistoryRef = useRef<number[]>([]);
  const lastStableFacesCountRef = useRef(1);
  const lastBrightness01Ref = useRef<number | null>(null);
  const brightnessFrameCounterRef = useRef(0);
  const multipleFacesConfirmedRef = useRef(false);
  /** Échantillons consécutifs avec ≥ 2 visages détectés (hors frames ignorées). */
  const multiFaceSampleStreakRef = useRef(0);
  /** Dernière fois qu’une alerte UI proctoring a été affichée (tous types confondus). */
  const lastAnyProctoringAlertAtRef = useRef(0);
  /** Timestamps document.visibilityState === "hidden" pour l’alerte onglet. */
  const tabHiddenTimestampsRef = useRef<number[]>([]);
  /** Heartbeats consécutifs avec regard ≠ centre (échantillon heartbeat). */
  const gazeNonCenterHeartbeatStreakRef = useRef(0);

  const pushWarning = useCallback(
    (id: string, message: string, severity: OralProctoringWarning["severity"] = "warn") => {
      setWarnings((prev) => {
        if (prev.some((p) => p.id === id)) return prev;
        return [...prev, { id, message, severity }].slice(-8);
      });
    },
    [],
  );

  const pushWarningThrottled = useCallback(
    (id: string, message: string, severity: OralProctoringWarning["severity"] = "warn") => {
      const now = Date.now();
      if (now - lastAnyProctoringAlertAtRef.current < ALERT_COOLDOWN_MS) return;
      lastAnyProctoringAlertAtRef.current = now;
      pushWarning(id, message, severity);
    },
    [pushWarning],
  );

  const dismissWarning = useCallback((id: string) => {
    setWarnings((prev) => prev.filter((w) => w.id !== id));
  }, []);

  const send = useCallback(
    async (eventType: string, metadata: Record<string, unknown> = {}) => {
      const oralSession = accessToken?.trim() || getOralInterviewAccessToken()?.trim();
      if (!oralSession) {
        console.warn("[PROCTORING] send skipped: no oral session token", { event_type: eventType });
        return;
      }
      if (import.meta.env.DEV) {
        console.log("PROCTORING PAYLOAD:", { event_type: eventType, metadata });
      }
      try {
        const data = await postProctoring(oralSession, eventType, metadata);
        if (data == null && eventType === "gaze_heartbeat") {
          console.warn("[PROCTORING] gaze_heartbeat not sent (missing oral session token)");
        }
        const cw = data?.candidate_warning;
        if (cw?.id && cw.message) {
          if (cw.id === "fs") {
            return;
          }
          const warnId = String(cw.id);
          if (SILENCED_PHONE_WARNING_IDS.has(warnId) || warnId.startsWith("phone")) {
            console.log("[PHONE DETECTED - SILENT]", { event_type: eventType, candidate_warning: cw });
            dismissWarning("phone");
            dismissWarning("phone_hb");
            return;
          }
          if (cw.id.startsWith("gaze_") && gazeNonCenterHeartbeatStreakRef.current < GAZE_ALERT_MIN_CONSECUTIVE_HEARTBEATS) {
            return;
          }
          const sev: OralProctoringWarning["severity"] =
            cw.severity === "info" ? "info" : "warn";
          const message =
            cw.id === "tab" ? TAB_VISIBILITY_MESSAGE : cw.message;
          if (cw.id === "tab" && document.visibilityState !== "hidden") {
            return;
          }
          pushWarningThrottled(cw.id, message, sev);
          if (sev === "info") {
            window.setTimeout(() => dismissWarning(cw.id), 7000);
          }
        }
      } catch (e) {
        if (import.meta.env.DEV) {
          console.warn("[oral-proctoring] proctoring-event failed", eventType, e);
        }
      }
    },
    [accessToken, pushWarningThrottled, dismissWarning],
  );

  useEffect(() => {
    const oralReady = Boolean(accessToken?.trim() || getOralInterviewAccessToken()?.trim());
    if (!enabled || !oralReady) return;

    const tok = (accessToken?.trim() || getOralInterviewAccessToken()?.trim() || "").trim();
    if (sessionTokenRef.current !== tok) {
      sessionTokenRef.current = tok;
      console.info("[PROCTORING] enabled (new session token)");
      void send("session_start", {});
    } else {
      console.info("[PROCTORING] enabled");
    }

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        const ts = Date.now();
        void send("visibility_hidden", {
          detail: "document_hidden",
          tab_switch: true,
          timestamp: ts,
        });
        const recent = tabHiddenTimestampsRef.current.filter((t) => ts - t <= TAB_ALERT_WINDOW_MS);
        recent.push(ts);
        tabHiddenTimestampsRef.current = recent;
        if (recent.length >= 2) {
          pushWarningThrottled("tab", TAB_VISIBILITY_MESSAGE, "info");
        }
      } else {
        dismissWarning("tab");
      }
    };

    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, accessToken, send, pushWarningThrottled, dismissWarning]);

  useEffect(() => {
    const oralReady = Boolean(accessToken?.trim() || getOralInterviewAccessToken()?.trim());
    if (!enabled || !oralReady) return;

    // Init MediaPipe Tasks Vision (optionnel). Ne bloque pas : fallback FaceDetector conservé.
    if (!mpInitOnceRef.current) {
      mpInitOnceRef.current = true;
      void (async () => {
        try {
          const mod = await import("@mediapipe/tasks-vision");
          const FilesetResolver = (mod as any).FilesetResolver;
          const FaceLandmarker = (mod as any).FaceLandmarker;
          if (!FilesetResolver || !FaceLandmarker) {
            console.log("[MEDIAPIPE] init fail (exports missing)");
            return;
          }
          const vision = await FilesetResolver.forVisionTasks(
            // WASM depuis CDN (plus fiable que servir depuis node_modules en prod)
            "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm",
          );
          const faceLandmarker = await FaceLandmarker.createFromOptions(vision, {
            baseOptions: {
              // Modèle standard ; CDN = évite gestion d’assets Vite
              modelAssetPath:
                "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
              delegate: "GPU",
            },
            outputFaceBlendshapes: false,
            outputFacialTransformationMatrixes: true,
            runningMode: "VIDEO",
            numFaces: 4,
          });
          mpRef.current = {
            faceLandmarker,
            detectForVideo: (video: HTMLVideoElement, nowMs: number) =>
              (faceLandmarker as any).detectForVideo(video, nowMs),
          };
          console.log("[MEDIAPIPE] init ok", { hasFaceLandmarker: true });
        } catch (e) {
          mpRef.current = null;
          console.log("[MEDIAPIPE] init fail", e);
        }
      })();
    }

    faceDetectorRef.current = null;
    const Ctor = getFaceDetectorCtor();
    const detectorCtorAvailable = Boolean(Ctor);
    console.log("[DETECTOR] available:", detectorCtorAvailable);
    if (!Ctor) {
      console.log("[PROCTORING] DETECTOR INIT FAIL (API absente)");
      console.warn(
        "[PROCTORING] FaceDetector indisponible — les heartbeats enverront faces_count=0 et regard « unknown » (pas de faux centre).",
      );
    } else {
      try {
        faceDetectorRef.current = new Ctor({ maxDetectedFaces: 4, fastMode: true });
        console.log("[PROCTORING] DETECTOR INIT OK");
      } catch (e) {
        faceDetectorRef.current = null;
        console.log("[PROCTORING] DETECTOR INIT FAIL (constructeur)");
        console.error("[DETECTOR] error:", e);
      }
    }

    const resolveVideo = () => getVideoElement?.() ?? videoRef.current;

    let intervalsStarted = false;
    let gazeIntervalId = 0;
    let hbIntervalId = 0;
    let videoWaitTimer = 0;

    const clearVideoWait = () => {
      if (videoWaitTimer) {
        window.clearTimeout(videoWaitTimer);
        videoWaitTimer = 0;
      }
    };

    /**
     * `loadedmetadata` : log strict + démarrage des intervalles (via callback).
     * `canplay` / `playing` : relance échantillonnage quand la frame est disponible (readyState peut passer ≥ 2).
     */
    const attachVideoMediaListeners = (
      video: HTMLVideoElement,
      onMediaEvent: () => void,
      onLoadedMetadata?: () => void,
    ) => {
      if (videoListenersAttachedRef.current === video) return;

      videoListenerAbortRef.current?.abort();
      const ac = new AbortController();
      videoListenerAbortRef.current = ac;
      videoListenersAttachedRef.current = video;

      video.addEventListener(
        "loadedmetadata",
        () => {
          console.log("[PROCTORING] VIDEO READY", video.readyState);
          console.log("[VIDEO] readyState (proctoring):", video.readyState);
          console.log("[VIDEO] dimensions (proctoring):", video.videoWidth, video.videoHeight);
          onLoadedMetadata?.();
          onMediaEvent();
        },
        { signal: ac.signal },
      );
      video.addEventListener("canplay", () => onMediaEvent(), { signal: ac.signal });
      video.addEventListener("playing", () => onMediaEvent(), { signal: ac.signal });
    };

    let gazeSampleBusy = false;
    let runGazeSampleImpl: () => Promise<void>;
    /** Limite le bruit console pour [DETECTOR] detect result */
    let lastDetectorResultLogAt = 0;
    let lastGazeAnalysisLogAt = 0;
    let lastPhoneDebugLogAt = 0;

    const runGazeSample = async () => {
      if (gazeSampleBusy) return;
      gazeSampleBusy = true;
      try {
        await runGazeSampleImpl();
      } finally {
        gazeSampleBusy = false;
      }
    };

    /** Pas de modèle de détection d’objets : posture / regard seulement. Seuil 0,25 aligné backend. */
    const attemptForcedPhoneDetected = (metaLike: Record<string, unknown>): boolean => {
      const nowT = Date.now();
      if (nowT - lastPhoneDetectedSentAtRef.current < PHONE_EVENT_COOLDOWN_MS) return false;

      const ppsRaw = metaLike.phone_posture_score;
      const pps =
        typeof ppsRaw === "number" && Number.isFinite(ppsRaw) ? ppsRaw : Number(ppsRaw ?? 0);
      const pstRaw = metaLike.phone_posture_streak;
      const pstk =
        typeof pstRaw === "number" && Number.isFinite(pstRaw)
          ? Math.round(pstRaw)
          : Math.round(Number(pstRaw ?? 0));
      const win = lastGazeWindowMetricsRef.current;
      const downRatio =
        typeof metaLike.gaze_down_ratio === "number" && Number.isFinite(metaLike.gaze_down_ratio)
          ? metaLike.gaze_down_ratio
          : (win?.gaze_down_ratio ?? 0);
      const robjs = Array.isArray(metaLike.objects) ? (metaLike.objects as unknown[]) : [];
      const hasStrictObj = robjs.some((o) => {
        const s = String(o).toLowerCase().trim();
        return (
          s.includes("phone") ||
          s === "cell" ||
          s === "mobile" ||
          s === "smartphone" ||
          s.includes("cell phone")
        );
      });
      const strictShape =
        Number.isFinite(pps) &&
        pps >= PHONE_STRICT_COMBINED_MIN &&
        pstk >= PHONE_STRICT_STREAK_MIN &&
        downRatio >= PHONE_STRICT_DOWN_RATIO_MIN;
      const evidenceOk =
        hasStrictObj ||
        phoneStrictSampleStreakRef.current >= PHONE_STRICT_SAMPLE_TICKS ||
        phoneStrictHeartbeatStreakRef.current >= 3 ||
        (strictShape &&
          phoneStrictSampleStreakRef.current >= PHONE_STRICT_SAMPLE_TICKS &&
          phoneStrictHeartbeatStreakRef.current >= 2);
      if (!evidenceOk) return false;

      phoneDetectedLatchRef.current = true;
      lastPhoneDetectedSentAtRef.current = nowT;
      const metadata: Record<string, unknown> = {
        phone_detected: true,
        phone_suspected: true,
        phone_posture_score: round3(Number.isFinite(pps) ? pps : 0),
        phone_posture_streak: Math.max(0, pstk),
        phone_confidence: round3(Number.isFinite(pps) ? pps : 0),
        objects: hasStrictObj ? ["phone"] : [],
        source: "frontend_phone_strict",
        timestamp: nowT,
      };
      console.log("[PHONE DETECTED - SILENT]", metadata);
      void send("phone_detected", metadata);
      return true;
    };

    const flushHeartbeatToBackend = () => {
      const now = Date.now();
      let meta = proctoringStateRef.current;
      if (!meta || Object.keys(meta).length === 0) {
        meta = {
          gaze_direction: "unknown",
          gaze_region: "unknown",
          faces_count: 0,
          face_visible: false,
          face_detected: false,
          rapid_motion: false,
          objects: [],
          face_detector_available: false,
          timestamp: now,
          tab_switch: false,
          fullscreen_exit: false,
        };
        proctoringStateRef.current = meta;
      }
      const prevWin = lastGazeWindowMetricsRef.current;
      const metaVideoNotReady = (meta as { video_not_ready?: boolean }).video_not_ready === true;
      const metaMerged =
        prevWin && metaVideoNotReady
          ? {
              ...meta,
              gaze_center_ratio: prevWin.gaze_center_ratio,
              gaze_left_ratio: prevWin.gaze_left_ratio,
              gaze_right_ratio: prevWin.gaze_right_ratio,
              gaze_up_ratio: prevWin.gaze_up_ratio,
              gaze_down_ratio: prevWin.gaze_down_ratio,
              gaze_off_ratio: prevWin.gaze_off_ratio,
              dominant_gaze_direction: prevWin.dominant_gaze_direction,
              gaze_quality_score: prevWin.gaze_quality_score,
              gaze_quality_label: prevWin.gaze_quality_label,
              suspicious_gaze: prevWin.suspicious_gaze,
            }
          : { ...meta };
      const mm = metaMerged as Record<string, unknown>;
      const vn = mm.video_not_ready === true;
      const fv = mm.face_visible === true;
      if (vn || !fv) {
        presenceMissingHbCountRef.current += 1;
        presenceGoodStreakRef.current = 0;
      } else {
        presenceGoodStreakRef.current += 1;
        if (presenceGoodStreakRef.current >= 2) {
          presenceMissingHbCountRef.current = 0;
        }
      }
      const sustainedPresence =
        presenceMissingHbCountRef.current >= PRESENCE_ANOMALY_HEARTBEATS_REQUIRED;
      mm.presence_anomaly_detected = sustainedPresence;

      const fcRaw = mm.faces_count;
      const fcHb =
        typeof fcRaw === "number" && !Number.isNaN(fcRaw) ? Math.max(0, Math.trunc(fcRaw)) : 0;
      if (fcHb >= 2) {
        multiFaceHbStreakRef.current += 1;
      } else {
        multiFaceHbStreakRef.current = 0;
      }
      mm.multiple_faces_confirmed = multipleFacesConfirmedRef.current;

      const hbPayload = buildProctoringHeartbeatPayload({
        ...mm,
        timestamp: now,
      });
      lastHeartbeatSentAtRef.current = now;
      const domHb = String(hbPayload.dominant_gaze_direction ?? "")
        .trim()
        .toLowerCase();
      if (domHb === "down") {
        phoneDownDominantHbStreakRef.current += 1;
      } else {
        phoneDownDominantHbStreakRef.current = 0;
      }
      if (lastStrictPhoneFrameRef.current) {
        phoneStrictHeartbeatStreakRef.current += 1;
      } else {
        phoneStrictHeartbeatStreakRef.current = 0;
      }
      attemptForcedPhoneDetected(hbPayload as Record<string, unknown>);

      const gzHb = String(
        hbPayload.gaze_direction ?? hbPayload.gaze_region ?? "unknown",
      )
        .trim()
        .toLowerCase();
      if (gzHb === "center") {
        gazeNonCenterHeartbeatStreakRef.current = 0;
        dismissWarning("gaze_screen");
      } else {
        gazeNonCenterHeartbeatStreakRef.current += 1;
        if (gazeNonCenterHeartbeatStreakRef.current >= GAZE_ALERT_MIN_CONSECUTIVE_HEARTBEATS) {
          pushWarningThrottled(
            "gaze_screen",
            "Merci de regarder vers l’écran / la caméra lorsque vous répondez.",
            "info",
          );
        }
      }

      if (sustainedPresence) {
        if (!presenceAnomalyEpisodeActiveRef.current) {
          const nowMs = Date.now();
          if (nowMs - lastPresenceAnomalySentAtRef.current > PRESENCE_ANOMALY_COOLDOWN_MS) {
            lastPresenceAnomalySentAtRef.current = nowMs;
            presenceAnomalyEpisodeActiveRef.current = true;
            const metaSend = {
              presence_anomaly_detected: true,
              faces_count: fcHb,
              face_detected: Boolean(mm.face_detected),
              gaze_direction: String(mm.gaze_direction ?? mm.gaze_region ?? "unknown"),
              reason: vn ? "video_not_ready" : "face_missing",
              source: "frontend_heartbeat",
              timestamp: nowMs,
            };
            console.log("[PRESENCE ANOMALY SENT]", metaSend);
            void send("presence_anomaly", metaSend);
          }
        }
      } else {
        presenceAnomalyEpisodeActiveRef.current = false;
      }

      console.log("[PROCTORING DEBUG]", {
        face_visible: hbPayload.face_visible,
        faces_count: hbPayload.faces_count,
        presenceMissingCount: presenceMissingHbCountRef.current,
        multipleFacesConfirmed: multipleFacesConfirmedRef.current,
      });
      console.log("[PROCTORING REAL PAYLOAD]", {
        event_type: "gaze_heartbeat",
        faces_count: hbPayload.faces_count,
        face_detected: hbPayload.face_detected,
        face_visible: hbPayload.face_visible,
        gaze_direction: hbPayload.gaze_direction,
        gaze_region: hbPayload.gaze_region,
        phone_detected: hbPayload.phone_detected,
        phone_suspected: hbPayload.phone_suspected,
        phone_posture_score: hbPayload.phone_posture_score,
        presence_anomaly_detected: hbPayload.presence_anomaly_detected,
        face_detector_available: hbPayload.face_detector_available,
        camera_inference_unavailable: hbPayload.camera_inference_unavailable,
        video_not_ready: hbPayload.video_not_ready,
        video_ready_state: hbPayload.video_ready_state,
        objects: hbPayload.objects,
      });
      console.log("[PROCTORING PAYLOAD SENT]", hbPayload);
      void send("gaze_heartbeat", hbPayload);
    };

    const startIntervals = () => {
      if (intervalsStarted) return;
      intervalsStarted = true;
      gazeIntervalId = window.setInterval(() => {
        void runGazeSample();
      }, GAZE_SAMPLE_INTERVAL_MS);
      hbIntervalId = window.setInterval(() => {
        void (async () => {
          await runGazeSample();
          flushHeartbeatToBackend();
        })();
      }, PROCTORING_HEARTBEAT_INTERVAL_MS);
      void (async () => {
        await runGazeSample();
        flushHeartbeatToBackend();
      })();
    };

    const scheduleUntilVideoMetadata = () => {
      const v = resolveVideo();
      if (!v) {
        videoWaitTimer = window.setTimeout(scheduleUntilVideoMetadata, 80);
        return;
      }
      videoWaitTimer = 0;

      attachVideoMediaListeners(
        v,
        () => {
          void runGazeSample();
        },
        () => {
          if (!intervalsStarted) startIntervals();
        },
      );

      if (v.readyState >= HTMLMediaElement.HAVE_METADATA) {
        console.log("[PROCTORING] VIDEO READY", v.readyState);
        if (!intervalsStarted) startIntervals();
        void runGazeSample();
      }
    };

    runGazeSampleImpl = async () => {
      const video = resolveVideo();
      if (import.meta.env.DEV) {
        console.info("[PROCTORING] videoRef current", {
          hasVideo: Boolean(video),
          readyState: video?.readyState,
          hasSrcObject: Boolean(video?.srcObject),
        });
      }

      if (!video) {
        const payload = {
          faces_count: 0,
          face_visible: false,
          face_detected: false,
          gaze_region: "unknown",
          gaze_direction: "unknown",
          confidence: 0,
          rapid_motion: false,
          objects: [] as string[],
          video_element_missing: true,
          timestamp: Date.now(),
          tab_switch: false,
          fullscreen_exit: false,
          other_person_detected: false,
          face_detector_available: false,
        };
        proctoringStateRef.current = payload;
        console.log("[GAZE] video_element_missing:", payload);
        return;
      }

      attachVideoMediaListeners(
        video,
        () => {
          void runGazeSample();
        },
        () => {
          if (!intervalsStarted) startIntervals();
        },
      );

      ensureVideoPlaybackAttempt(video);
      lastVideoReadyStateRef.current = video.readyState;

      const detectorAvailable = Boolean(faceDetectorRef.current);
      const dimsOk = video.videoWidth > 16 && video.videoHeight > 16;
      /**
       * Avec FaceDetector / MediaPipe : attendre HAVE_CURRENT_DATA (≥2) pour des frames exploitables.
       * Sans détecteur exploitable mais vidéo dimensionnée : on échantillonne quand même pour envoyer
       * faces_count=0 / regard unknown (pas de faux « centre » ni visage fictif).
       */
      const canSampleVideo =
        video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA ||
        (!detectorAvailable &&
          video.readyState >= HTMLMediaElement.HAVE_METADATA &&
          dimsOk);

      if (!canSampleVideo) {
        console.info("[PROCTORING] video not ready for sampling", {
          readyState: video.readyState,
          HAVE_METADATA: HTMLMediaElement.HAVE_METADATA,
          HAVE_CURRENT_DATA: HTMLMediaElement.HAVE_CURRENT_DATA,
          hasSrcObject: Boolean(video.srcObject),
          videoWidth: video.videoWidth,
          videoHeight: video.videoHeight,
          detectorAvailable,
          canSampleVideo,
        });
        const payload = {
          faces_count: 0,
          face_visible: false,
          face_detected: false,
          gaze_region: "unknown",
          gaze_direction: "unknown",
          confidence: 0,
          rapid_motion: false,
          objects: [] as string[],
          video_not_ready: true,
          video_ready_state: video.readyState,
          timestamp: Date.now(),
          tab_switch: false,
          fullscreen_exit: false,
          other_person_detected: false,
          face_detector_available: detectorAvailable,
        };
        proctoringStateRef.current = payload;
        console.log("[GAZE] video_not_ready:", payload);
        return;
      }

      let detectorUsedOk = false;
      let facesCount = 0;
      let gaze: GazeDirection = "unknown";
      let gazeConfidence = 0.45;
      let faceVisible = false;
      let rapidMotion = false;
      let phonePostureScoreLast: number | undefined;
      let gazeRatio: number | undefined;
      let headYaw: number | undefined;
      let headPitch: number | undefined;
      let suspiciousHeadMovement = false;
      let suspiciousGazeRatio = false;
      let mpUsedOk = false;

      const mp = mpRef.current;
      if (mp?.detectForVideo) {
        try {
          const nowMs = Date.now();
          const res = await mp.detectForVideo(video, nowMs);
          const landmarks = res?.faceLandmarks as Array<Array<{ x: number; y: number }>> | undefined;
          if (Array.isArray(landmarks)) {
            mpUsedOk = true;
            facesCount = landmarks.length;
            faceVisible = facesCount >= 1;
            if (facesCount >= 2) {
              lastFaceCenterY.current = null;
              phoneDownStepStreak.current = 0;
              phoneSuspicionStreak.current = 0;
              gazeStateRef.current = createInitialGazeState();
            }
            if (facesCount === 1 && landmarks[0]) {
              const g = mpGazeFromLandmarks(landmarks[0]);
              if (g.gaze_ratio !== undefined) {
                gazeRatio = g.gaze_ratio;
                suspiciousGazeRatio =
                  gazeRatio < GAZE_RATIO_SUSPICION_LOW || gazeRatio > GAZE_RATIO_SUSPICION_HIGH;
              }
              if (g.gaze_direction) {
                gaze = g.gaze_direction;
                // Confiance : mappe qualité [0..1] vers [0.25..0.95]
                gazeConfidence = 0.25 + g.quality * 0.7;
              }

              const mats = res?.facialTransformationMatrixes as Array<{ data?: number[] }> | undefined;
              const m0 = mats && mats[0] && Array.isArray(mats[0].data) ? mats[0].data : undefined;
              if (m0) {
                const yp = matrixYawPitchDeg(m0);
                if (yp) {
                  headYaw = round3(yp.yaw);
                  headPitch = round3(yp.pitch);
                  suspiciousHeadMovement = Math.abs(headYaw) > 12 || headPitch > 15;
                }
              }

              // Posture « téléphone » : même heuristique bbox que FaceDetector (pas de détection d’objet YOLO).
              const bLm = landmarksToVideoBoundingBox(landmarks[0], video);
              if (bLm.width >= 8 && bLm.height >= 8) {
                const metricsMp = computeFaceFrameMetrics(video, bLm);
                const prevYMp = lastFaceCenterY.current;
                if (prevYMp !== null) {
                  if (metricsMp.faceCenterY > prevYMp + 0.017) {
                    phoneDownStepStreak.current += 1;
                  } else if (metricsMp.faceCenterY < prevYMp - 0.012) {
                    phoneDownStepStreak.current = 0;
                  } else {
                    phoneDownStepStreak.current = Math.max(0, phoneDownStepStreak.current - 1);
                  }
                }
                lastFaceCenterY.current = metricsMp.faceCenterY;

                const postureCoreMp = computePhonePostureCore(
                  metricsMp,
                  gaze,
                  phoneDownStepStreak.current,
                );
                if (postureCoreMp >= PHONE_POSTURE_SUSPICION_THRESHOLD) {
                  phoneSuspicionStreak.current += 1;
                } else {
                  phoneSuspicionStreak.current = Math.max(0, phoneSuspicionStreak.current - 1);
                }
                const phonePostureScoreMp = computePhonePostureScore(
                  postureCoreMp,
                  phoneSuspicionStreak.current,
                );
                phonePostureScoreLast = phonePostureScoreMp;

                const nowMsMp = Date.now();
                if (
                  phoneSuspicionStreak.current >= 2 &&
                  phonePostureScoreMp >= PHONE_POSTURE_REPORT_THRESHOLD &&
                  nowMsMp - lastPhoneSuspectedSent.current > 4500
                ) {
                  lastPhoneSuspectedSent.current = nowMsMp;
                  void send("phone_suspected", {
                    active: true,
                    score: phonePostureScoreMp,
                    phone_posture_score: phonePostureScoreMp,
                    phone_confidence: phonePostureScoreMp,
                    reason: "phone_posture_composite",
                  });
                }
              }
            }
          }
        } catch (e) {
          mpUsedOk = false;
        }
      }

      const det = faceDetectorRef.current;
      if (!mpUsedOk && det) {
        try {
          const faces = (await det.detect(video)) as Array<{ boundingBox: DOMRectReadOnly }>;
          detectorUsedOk = true;
          facesCount = faces.length;
          const nowLog = Date.now();
          if (nowLog - lastDetectorResultLogAt > 2500) {
            lastDetectorResultLogAt = nowLog;
            console.log("[DETECTOR] detect result:", faces.length);
          }
          faceVisible = facesCount >= 1;
          if (facesCount >= 2) {
            lastFaceCenterY.current = null;
            phoneDownStepStreak.current = 0;
            phoneSuspicionStreak.current = 0;
            gazeStateRef.current = createInitialGazeState();
          } else {
            dismissWarning("multi");
          }

          if (facesCount === 1) {
            const b = faces[0].boundingBox;
            const { nx, ny, areaRatio } = bboxToNorm(video, b);
            const upd = updateStableGaze(gazeStateRef.current, nx, ny, areaRatio);
            gazeStateRef.current = upd.nextState;
            gaze = upd.direction;
            gazeConfidence = upd.confidence;

            if (gaze === "left" || gaze === "right" || gaze === "up" || gaze === "down") {
              gazeOffAxisStreak.current += 1;
            } else {
              gazeOffAxisStreak.current = 0;
            }

            const metrics = computeFaceFrameMetrics(video, b);
            const prevY = lastFaceCenterY.current;
            if (prevY !== null) {
              if (metrics.faceCenterY > prevY + 0.017) {
                phoneDownStepStreak.current += 1;
              } else if (metrics.faceCenterY < prevY - 0.012) {
                phoneDownStepStreak.current = 0;
              } else {
                phoneDownStepStreak.current = Math.max(0, phoneDownStepStreak.current - 1);
              }
            }
            lastFaceCenterY.current = metrics.faceCenterY;

            const postureCore = computePhonePostureCore(metrics, gaze, phoneDownStepStreak.current);
            if (postureCore >= PHONE_POSTURE_SUSPICION_THRESHOLD) {
              phoneSuspicionStreak.current += 1;
            } else {
              phoneSuspicionStreak.current = Math.max(0, phoneSuspicionStreak.current - 1);
            }
            const phonePostureScore = computePhonePostureScore(
              postureCore,
              phoneSuspicionStreak.current,
            );
            phonePostureScoreLast = phonePostureScore;

            const nowMs = Date.now();
            if (
              phoneSuspicionStreak.current >= 2 &&
              phonePostureScore >= PHONE_POSTURE_REPORT_THRESHOLD &&
              nowMs - lastPhoneSuspectedSent.current > 4500
            ) {
              lastPhoneSuspectedSent.current = nowMs;
              void send("phone_suspected", {
                active: true,
                score: phonePostureScore,
                phone_posture_score: phonePostureScore,
                phone_confidence: phonePostureScore,
                reason: "phone_posture_composite",
              });
            }

            const cur = { x: b.left, y: b.top, w: b.width, h: b.height };
            const prev = lastBbox.current;
            if (prev) {
              const dx = Math.abs(cur.x - prev.x);
              const dy = Math.abs(cur.y - prev.y);
              if (dx + dy > (video.clientWidth || 640) * 0.18) {
                rapidMotion = true;
                void send("suspicious_motion", { detail: "rapid_face_shift" });
              }
            }
            lastBbox.current = cur;
          } else {
            lastBbox.current = null;
            lastFaceCenterY.current = null;
            phoneDownStepStreak.current = 0;
            phoneSuspicionStreak.current = 0;
            gazeStateRef.current = createInitialGazeState();
            if (facesCount === 0) {
              gaze = "off";
              gazeConfidence = 0.2;
            } else {
              gaze = "unknown";
            }
          }
        } catch (err) {
          detectorUsedOk = false;
          console.error("[DETECTOR] error:", err);
        }
      }

      /**
       * Sans MediaPipe ni FaceDetector exploitable : ne pas inventer visage/regard « centre ».
       * Le backend agrège alors absence de visage / regard inconnu (pas de faux positifs stabilité).
       */
      if (canSampleVideo && !detectorUsedOk && !mpUsedOk) {
        console.warn(
          "[PROCTORING] Inférence visage indisponible — pas de fallback center/1 face",
          {
            readyState: video.readyState,
            detectorCtorPresent: detectorAvailable,
            dimsOk,
          },
        );
        lastBbox.current = null;
        lastFaceCenterY.current = null;
        phoneDownStepStreak.current = 0;
        phoneSuspicionStreak.current = 0;
        gazeStateRef.current = createInitialGazeState();
        facesCount = 0;
        faceVisible = false;
        gaze = "unknown";
        gazeConfidence = 0.2;
      }

      const detectionFacesCount = facesCount;

      gaze = normalizeGazeDirection(gaze);

      pushGazeWindowSample(gazeWindowBufferRef.current, gaze, rapidMotion);
      const win = analyzeGazeWindow(gazeWindowBufferRef.current);

      brightnessFrameCounterRef.current += 1;
      let br01 = lastBrightness01Ref.current;
      if (brightnessFrameCounterRef.current % 3 === 0) {
        br01 = sampleVideoBrightness01(video);
        if (br01 !== null) lastBrightness01Ref.current = br01;
      }
      const vwGeom = video.videoWidth || 0;
      const rapidWinGeom = win.window_rapid_ratio;
      const ignoreFaceGeom =
        (vwGeom > 0 && vwGeom < PROCTORING_VIDEO_WIDTH_MIN) ||
        rapidWinGeom > PROCTORING_WINDOW_RAPID_IGNORE ||
        (br01 !== null && br01 < PROCTORING_BRIGHTNESS_MIN);

      if (!ignoreFaceGeom) {
        const fh = facesHistoryRef.current;
        fh.push(detectionFacesCount);
        if (fh.length > FACES_HISTORY_MAX) fh.shift();
        lastStableFacesCountRef.current = Math.max(0, Math.min(4, detectionFacesCount));
      }

      const fhRead = facesHistoryRef.current;
      const twoPlus = fhRead.filter((x) => x >= 2).length;
      const multiHistOk = fhRead.length >= 3 && twoPlus * 2 > fhRead.length;

      if (!ignoreFaceGeom && detectionFacesCount >= 2) {
        multiFaceSampleStreakRef.current += 1;
      } else {
        multiFaceSampleStreakRef.current = 0;
      }

      facesCount =
        ignoreFaceGeom && detectionFacesCount > 0
          ? lastStableFacesCountRef.current
          : detectionFacesCount;
      faceVisible = facesCount >= 1;

      multipleFacesConfirmedRef.current =
        multiFaceSampleStreakRef.current >= MULTI_FACE_MIN_CONSECUTIVE_SAMPLES &&
        multiHistOk &&
        !ignoreFaceGeom &&
        detectionFacesCount >= 2;

      if (multipleFacesConfirmedRef.current) {
        const nowMsMf = Date.now();
        if (nowMsMf - lastOtherPersonSent.current > 4500) {
          lastOtherPersonSent.current = nowMsMf;
          void send("other_person_detected", {
            active: true,
            faces_count: facesCount,
            other_person_detected: true,
            persons_count: facesCount,
          });
          void send("other_person_suspected", { active: true, faces_count: facesCount });
        }
        pushWarningThrottled(
          "multi",
          "Plusieurs visages détectés : une autre personne semble présente.",
          "warn",
        );
      } else if (facesCount < 2) {
        dismissWarning("multi");
      }

      if (detectorUsedOk && facesCount === 0) {
        noFaceStreak.current += 1;
        if (noFaceStreak.current >= 4) {
          pushWarningThrottled("face", "Gardez votre visage visible face à la caméra.", "warn");
        }
      } else {
        noFaceStreak.current = 0;
        dismissWarning("face");
      }

      const streakNorm = Math.min(1, phoneSuspicionStreak.current / 4);
      const windowPhone = computeWindowPhonePostureScore(
        win.gaze_down_ratio,
        win.gaze_left_ratio,
        win.gaze_right_ratio,
        win.window_rapid_ratio,
        streakNorm,
      );
      const framePps = phonePostureScoreLast ?? 0;
      const combinedPhonePosture = Math.round(Math.max(framePps, windowPhone) * 1000) / 1000;
      const phonePostureStreakVal = phoneSuspicionStreak.current;
      const strictPhoneFrame =
        combinedPhonePosture >= PHONE_STRICT_COMBINED_MIN &&
        phonePostureStreakVal >= PHONE_STRICT_STREAK_MIN &&
        win.gaze_down_ratio >= PHONE_STRICT_DOWN_RATIO_MIN;
      lastStrictPhoneFrameRef.current = strictPhoneFrame;
      if (strictPhoneFrame) {
        phoneStrictSampleStreakRef.current += 1;
      } else {
        phoneStrictSampleStreakRef.current = 0;
      }

      const phoneStrictOk =
        phoneStrictSampleStreakRef.current >= PHONE_STRICT_SAMPLE_TICKS ||
        phoneStrictHeartbeatStreakRef.current >= 3;
      if (phoneStrictOk) {
        phoneDetectedLatchRef.current = true;
      }
      const phoneDetected = phoneDetectedLatchRef.current;

      const objects: string[] = [];

      const suspiciousGaze =
        Boolean(win.suspicious_gaze) || Boolean(suspiciousGazeRatio) || win.gaze_off_ratio > 0.5;

      if (suspiciousHeadMovement) {
        const nowMs = Date.now();
        if (nowMs - lastHeadMotionSentAtRef.current > 2600) {
          lastHeadMotionSentAtRef.current = nowMs;
          const evtPayload = {
            detail: "head_pose_suspicious",
            suspicious_head_movement: true,
            head_yaw: headYaw,
            head_pitch: headPitch,
            rapid_motion: rapidMotion,
            timestamp: nowMs,
          };
          console.log("[HEAD MOVEMENT DETECTED SENT]", evtPayload);
          void send("suspicious_motion", evtPayload);
        }
      }

      const faceDetected = facesCount >= 1;

      const payload: Record<string, unknown> = {
        faces_count: facesCount,
        face_visible: faceVisible,
        face_detected: faceDetected,
        gaze_region: gaze,
        gaze_direction: gaze,
        confidence: Math.round(gazeConfidence * 1000) / 1000,
        rapid_motion: rapidMotion,
        face_detector_available: detectorUsedOk || mpUsedOk,
        camera_inference_unavailable: !(detectorUsedOk || mpUsedOk),
        mediapipe_available: Boolean(mpRef.current),
        mediapipe_used: mpUsedOk,
        video_ready_state: lastVideoReadyStateRef.current,
        timestamp: Date.now(),
        tab_switch: false,
        fullscreen_exit: false,
        objects,
        gaze_center_ratio: win.gaze_center_ratio,
        gaze_left_ratio: win.gaze_left_ratio,
        gaze_right_ratio: win.gaze_right_ratio,
        gaze_up_ratio: win.gaze_up_ratio,
        gaze_down_ratio: win.gaze_down_ratio,
        gaze_off_ratio: win.gaze_off_ratio,
        dominant_gaze_direction: win.dominant_gaze_direction,
        gaze_quality_score: win.gaze_quality_score,
        gaze_quality_label: win.gaze_quality_label,
        suspicious_gaze: suspiciousGaze,
        gaze_ratio: gazeRatio,
        head_yaw: headYaw,
        head_pitch: headPitch,
        suspicious_head_movement: suspiciousHeadMovement,
        phone_posture_score: combinedPhonePosture,
        phone_confidence: combinedPhonePosture,
        phone_posture_streak: phonePostureStreakVal,
        phone_detected: phoneDetected,
        presence_anomaly_detected: false,
        multiple_faces_confirmed: multipleFacesConfirmedRef.current,
        ...((combinedPhonePosture >= 0.48 && phonePostureStreakVal >= 2) ||
        (combinedPhonePosture >= PHONE_STRICT_COMBINED_MIN && phonePostureStreakVal >= 3)
          ? { phone_suspected: true }
          : {}),
        ...(multipleFacesConfirmedRef.current
          ? { other_person_detected: true, persons_count: facesCount }
          : {}),
      };

      if (import.meta.env.DEV) {
        console.log("[GAZE] sample summary:", {
          gaze_direction: gaze,
          faces_count: facesCount,
          face_detected: payload.face_detected,
          rapid_motion: rapidMotion,
          face_detector_available: detectorUsedOk,
          video_ready_state: video.readyState,
          objects,
        });
        const nowLog = Date.now();
        if (nowLog - lastGazeAnalysisLogAt > 2200) {
          lastGazeAnalysisLogAt = nowLog;
          console.log("[GAZE ANALYSIS]", {
            ...win,
            buffer_len: gazeWindowBufferRef.current.length,
            instant_gaze: gaze,
            gaze_ratio: gazeRatio,
            head_yaw: headYaw,
            head_pitch: headPitch,
            suspicious_gaze_ratio: suspiciousGazeRatio,
            suspicious_head_movement: suspiciousHeadMovement,
            mediapipe_used: mpUsedOk,
          });
          console.log("[PHONE DETECTION]", {
            frame_phone_posture: framePps,
            window_phone_posture: windowPhone,
            combined_phone_posture: combinedPhonePosture,
            phone_posture_streak: phonePostureStreakVal,
            phone_detected: phoneDetected,
            window_rapid_ratio: win.window_rapid_ratio,
          });
        }
        const tDbg = Date.now();
        if (tDbg - lastPhoneDebugLogAt > 900) {
          lastPhoneDebugLogAt = tDbg;
          console.log("[PHONE DETECTION DEBUG]", {
            score: combinedPhonePosture,
            down_ratio: win.gaze_down_ratio,
            rapid_ratio: win.window_rapid_ratio,
            streak: phonePostureStreakVal,
            detected: phoneDetected,
            strict_phone_frame: strictPhoneFrame,
            window_phone_raw: windowPhone,
          });
        }
      }

      lastGazeWindowMetricsRef.current = win;
      proctoringStateRef.current = payload;
      const phoneEventSent = attemptForcedPhoneDetected(payload);
      const tRaw = Date.now();
      if (tRaw - lastPhoneRawDebugLogAtRef.current >= 750) {
        lastPhoneRawDebugLogAtRef.current = tRaw;
        console.log("[PHONE RAW DEBUG]", {
          phone_posture_score: combinedPhonePosture,
          phone_posture_streak: phonePostureStreakVal,
          phoneDetectedLatch: phoneDetectedLatchRef.current,
          objects,
          gaze_down_ratio: win.gaze_down_ratio,
          dominant_gaze_direction: win.dominant_gaze_direction,
          eventSent: phoneEventSent,
        });
      }
    };

    scheduleUntilVideoMetadata();

    return () => {
      clearVideoWait();
      if (gazeIntervalId) window.clearInterval(gazeIntervalId);
      if (hbIntervalId) window.clearInterval(hbIntervalId);
      gazeIntervalId = 0;
      hbIntervalId = 0;
      intervalsStarted = false;
      videoListenerAbortRef.current?.abort();
      videoListenerAbortRef.current = null;
      videoListenersAttachedRef.current = null;
      gazeWindowBufferRef.current.length = 0;
      lastGazeWindowMetricsRef.current = null;
      phoneDetectedLatchRef.current = false;
      phoneDownDominantHbStreakRef.current = 0;
      phoneStrictSampleStreakRef.current = 0;
      lastStrictPhoneFrameRef.current = false;
      phoneStrictHeartbeatStreakRef.current = 0;
      lastVideoReadyStateRef.current = 0;
      lastPhoneRawDebugLogAtRef.current = 0;
      presenceGoodStreakRef.current = 0;
      presenceAnomalyEpisodeActiveRef.current = false;
      lastPresenceAnomalySentAtRef.current = 0;
      presenceMissingHbCountRef.current = 0;
      multiFaceHbStreakRef.current = 0;
      facesHistoryRef.current.length = 0;
      lastStableFacesCountRef.current = 1;
      lastBrightness01Ref.current = null;
      brightnessFrameCounterRef.current = 0;
      multipleFacesConfirmedRef.current = false;
      multiFaceSampleStreakRef.current = 0;
      gazeNonCenterHeartbeatStreakRef.current = 0;
      tabHiddenTimestampsRef.current = [];
    };
  }, [enabled, accessToken, videoRef, getVideoElement, send, pushWarningThrottled, dismissWarning]);

  const endSession = useCallback(() => {
    void send("session_end", {});
  }, [send]);

  /** Plein écran désactivé (UX) ; la détection backend ne repose pas sur le plein écran côté UI. */
  const requestInterviewFullscreen = useCallback((_element: HTMLElement | null) => {}, []);

  return { warnings, dismissWarning, endSession, requestInterviewFullscreen };
}
