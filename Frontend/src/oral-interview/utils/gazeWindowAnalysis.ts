/**
 * Fenêtre glissante sur les échantillons de regard (≈14 s à 400 ms / échantillon)
 * pour ratios directionnels, qualité perçue, suspicion téléphone / regard.
 */
import type { GazeDirection } from "@/oral-interview/utils/gazeTracking";

export const GAZE_WINDOW_MAX_SAMPLES = 36;

export type GazeWindowSample = {
  direction: GazeDirection;
  rapid_motion: boolean;
};

export type GazeWindowMetrics = {
  gaze_center_ratio: number;
  gaze_left_ratio: number;
  gaze_right_ratio: number;
  gaze_up_ratio: number;
  gaze_down_ratio: number;
  gaze_off_ratio: number;
  gaze_unknown_ratio: number;
  dominant_gaze_direction: GazeDirection | string;
  gaze_quality_score: number;
  gaze_quality_label: string;
  suspicious_gaze: boolean;
  window_rapid_ratio: number;
};

function round4(n: number): number {
  return Math.round(n * 10000) / 10000;
}

/** Pousse un échantillon ; taille max `GAZE_WINDOW_MAX_SAMPLES`. */
export function pushGazeWindowSample(buf: GazeWindowSample[], direction: GazeDirection, rapid: boolean): void {
  buf.push({ direction, rapid_motion: rapid });
  const excess = buf.length - GAZE_WINDOW_MAX_SAMPLES;
  if (excess > 0) buf.splice(0, excess);
}

function countBuckets(buf: readonly GazeWindowSample[]): {
  center: number;
  left: number;
  right: number;
  up: number;
  down: number;
  off: number;
  unknown: number;
  rapidCount: number;
} {
  const c = { center: 0, left: 0, right: 0, up: 0, down: 0, off: 0, unknown: 0, rapidCount: 0 };
  for (const s of buf) {
    if (s.rapid_motion) c.rapidCount += 1;
    switch (s.direction) {
      case "center":
        c.center += 1;
        break;
      case "left":
        c.left += 1;
        break;
      case "right":
        c.right += 1;
        break;
      case "up":
        c.up += 1;
        break;
      case "down":
        c.down += 1;
        break;
      case "off":
        c.off += 1;
        break;
      default:
        c.unknown += 1;
    }
  }
  return c;
}

/**
 * Score téléphone agrégé fenêtre (0–1) : regard bas, latéral, mouvements rapides, streak.
 * Bonus si mouvements rapides + bas fréquents (usage type lecture basse).
 */
export function computeWindowPhonePostureScore(
  downRatio: number,
  leftRatio: number,
  rightRatio: number,
  rapidRatio: number,
  streakNorm01: number,
): number {
  const lateral = Math.max(leftRatio, rightRatio);
  const streak = Math.max(0, Math.min(1, streakNorm01));
  let score =
    downRatio * 0.5 +
    lateral * 0.2 +
    rapidRatio * 0.2 +
    streak * 0.1;
  if (rapidRatio > 0.3 && downRatio > 0.3) {
    score += 0.2;
  }
  return Math.round(Math.max(0, Math.min(1, score)) * 1000) / 1000;
}

export function analyzeGazeWindow(buf: readonly GazeWindowSample[]): GazeWindowMetrics {
  const n = buf.length;
  if (n === 0) {
    return {
      gaze_center_ratio: 0,
      gaze_left_ratio: 0,
      gaze_right_ratio: 0,
      gaze_up_ratio: 0,
      gaze_down_ratio: 0,
      gaze_off_ratio: 0,
      gaze_unknown_ratio: 1,
      dominant_gaze_direction: "unknown",
      gaze_quality_score: 0,
      gaze_quality_label: "données insuffisantes",
      suspicious_gaze: false,
      window_rapid_ratio: 0,
    };
  }

  const c = countBuckets(buf);
  const inv = 1 / n;
  const gaze_center_ratio = round4(c.center * inv);
  const gaze_left_ratio = round4(c.left * inv);
  const gaze_right_ratio = round4(c.right * inv);
  const gaze_up_ratio = round4(c.up * inv);
  const gaze_down_ratio = round4(c.down * inv);
  const gaze_off_ratio = round4(c.off * inv);
  const gaze_unknown_ratio = round4(c.unknown * inv);
  const window_rapid_ratio = round4(c.rapidCount * inv);

  const dirMap: Record<string, number> = {
    center: gaze_center_ratio,
    left: gaze_left_ratio,
    right: gaze_right_ratio,
    up: gaze_up_ratio,
    down: gaze_down_ratio,
    off: gaze_off_ratio,
    unknown: gaze_unknown_ratio,
  };
  let dominant_gaze_direction: GazeDirection | string = "unknown";
  let best = -1;
  for (const [k, v] of Object.entries(dirMap)) {
    if (v > best) {
      best = v;
      dominant_gaze_direction = k as GazeDirection;
    }
  }

  const suspicious_gaze =
    gaze_down_ratio > 0.4 ||
    gaze_off_ratio > 0.5 ||
    gaze_left_ratio > 0.45 ||
    gaze_right_ratio > 0.45 ||
    gaze_up_ratio > 0.45;

  const axisLoad = gaze_left_ratio + gaze_right_ratio + gaze_up_ratio + gaze_down_ratio;
  const dispersion =
    gaze_off_ratio * 0.42 +
    gaze_unknown_ratio * 0.18 +
    axisLoad * 0.28 +
    gaze_down_ratio * 0.12;
  const gaze_quality_score = Math.round(
    Math.max(0, Math.min(100, 100 * (gaze_center_ratio * 0.62 + (1 - Math.min(1, dispersion)) * 0.38))),
  );

  let gaze_quality_label: string;
  // Seuil abaissé : dès que quelques ratios existent, ils sont exploitables pour le rapport.
  // (évite d'afficher "données insuffisantes" alors que les ratios sont déjà stables)
  if (n < 3) {
    gaze_quality_label = "données insuffisantes";
  } else if (gaze_quality_score >= 72 && gaze_center_ratio >= 0.48 && gaze_off_ratio <= 0.22) {
    gaze_quality_label = "bonne";
  } else if (gaze_quality_score >= 48) {
    gaze_quality_label = "moyenne";
  } else {
    gaze_quality_label = "faible";
  }

  return {
    gaze_center_ratio,
    gaze_left_ratio,
    gaze_right_ratio,
    gaze_up_ratio,
    gaze_down_ratio,
    gaze_off_ratio,
    gaze_unknown_ratio,
    dominant_gaze_direction,
    gaze_quality_score,
    gaze_quality_label,
    suspicious_gaze,
    window_rapid_ratio,
  };
}
