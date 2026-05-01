/**
 * Heuristiques légères posture / téléphone (sans modèle lourd).
 * Coordonnées = espace intrinsèque de la vidéo (aligné FaceDetector).
 */

export type GazeRegion = "center" | "left" | "right" | "up" | "down" | "off" | "unknown";

export type FaceFrameMetrics = {
  /** Centre du visage, 0 = haut du cadre, 1 = bas */
  faceCenterY: number;
  faceCenterX: number;
  /** Aire du visage / aire de la vidéo */
  faceAreaRatio: number;
  aspectWidthOverHeight: number;
  /** (cy - milieu) / (h/2), même convention que le regard approximatif */
  normalizedNy: number;
};

export function computeFaceFrameMetrics(
  video: HTMLVideoElement,
  box: DOMRectReadOnly,
): FaceFrameMetrics {
  const vw = video.videoWidth || video.clientWidth || 1;
  const vh = video.videoHeight || video.clientHeight || 1;
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  return {
    faceCenterX: cx / vw,
    faceCenterY: cy / vh,
    faceAreaRatio: (box.width * box.height) / (vw * vh),
    aspectWidthOverHeight: box.width / Math.max(box.height, 1e-6),
    normalizedNy: (cy - vh / 2) / (vh / 2),
  };
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

/** Visage anormalement bas (souvent lecture d’un écran dans les mains / sur les genoux). */
function verticalLowFaceSignal(faceCenterY: number): number {
  if (faceCenterY >= 0.7) return 1;
  if (faceCenterY >= 0.6) return 0.72;
  if (faceCenterY >= 0.54) return 0.45;
  if (faceCenterY >= 0.48) return 0.18;
  return 0;
}

/** Visage trop petit = éloignement ou cadrage type mobile éloigné. */
function faceTooSmallSignal(faceAreaRatio: number): number {
  if (faceAreaRatio < 0.011) return 1;
  if (faceAreaRatio < 0.018) return 0.62;
  if (faceAreaRatio < 0.026) return 0.35;
  if (faceAreaRatio < 0.036) return 0.12;
  return 0;
}

/** Regard vers le bas (gaze + position verticale du centre du visage). */
function gazeDownCombinedSignal(gaze: GazeRegion, normalizedNy: number): number {
  if (gaze === "down") return 1;
  if (normalizedNy > 0.48) return 0.68;
  if (normalizedNy > 0.32) return 0.42;
  if (normalizedNy > 0.18) return 0.2;
  return 0;
}

/**
 * Répétition de frames « suspectes » (normalisée sur ~5 ticks).
 */
export function repetitionSignal(suspiciousStreak: number): number {
  return clamp01(suspiciousStreak / 5);
}

/**
 * Mouvement vers le bas répété (tête qui descend / oscillation vers le bas).
 * `downStepStreak` = nombre de ticks consécutifs où le centre du visage descend nettement.
 */
function downwardMotionSignal(downStepStreak: number): number {
  if (downStepStreak >= 4) return 1;
  if (downStepStreak >= 3) return 0.72;
  if (downStepStreak >= 2) return 0.45;
  if (downStepStreak >= 1) return 0.22;
  return 0;
}

/**
 * Score instantané sans historique de répétition (évite la circularité avec la streak).
 */
export function computePhonePostureCore(
  metrics: FaceFrameMetrics,
  gaze: GazeRegion,
  downStepStreak: number,
): number {
  const vert = verticalLowFaceSignal(metrics.faceCenterY);
  const size = faceTooSmallSignal(metrics.faceAreaRatio);
  const gazeD = gazeDownCombinedSignal(gaze, metrics.normalizedNy);
  const downM = downwardMotionSignal(downStepStreak);
  return clamp01(vert * 0.3 + size * 0.24 + gazeD * 0.28 + downM * 0.18);
}

/**
 * Score final 0–1 : noyau + pondération de la répétition de signaux suspects sur plusieurs ticks.
 */
export function computePhonePostureScore(
  coreScore: number,
  suspiciousStreak: number,
): number {
  const rep = repetitionSignal(suspiciousStreak);
  return clamp01(coreScore * 0.78 + rep * 0.22);
}

/** Seuil : au-dessus = tick « suspect » pour la streak de répétition. */
export const PHONE_POSTURE_SUSPICION_THRESHOLD = 0.46;

/** Seuil : envoi d’un événement `phone_suspected` si streak + score suffisant. */
export const PHONE_POSTURE_REPORT_THRESHOLD = 0.5;

/**
 * Score posture au-delà duquel on marque `phone_suspected` dans chaque `gaze_heartbeat`
 * (le backend cumule la preuve sans attendre uniquement l’événement dédié).
 */
export const PHONE_HEARTBEAT_EMBED_THRESHOLD = 0.42;
