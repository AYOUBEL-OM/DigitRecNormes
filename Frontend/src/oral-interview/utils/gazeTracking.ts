/**
 * Estimation du regard à partir de la position du visage dans le cadre (approximation tête / cadrage).
 * Lissage + stabilisation pour limiter le bruit frame à frame.
 */

export type GazeDirection = "center" | "left" | "right" | "up" | "down" | "off" | "unknown";

const SMOOTH_ALPHA = 0.34;
/** Nombre de frames consécutives avec la même direction « brute » lissée avant de valider le changement. */
export const GAZE_STABLE_FRAMES = 3;

const THR_X = 0.33;
const THR_Y_UP = 0.27;
const THR_Y_DOWN = 0.37;
/** Zone morte : proche du centre → regard centré (évite les oscillations). */
const DEAD_ZONE = 0.13;

const MIN_FACE_AREA = 0.011;

export type GazeStabilityState = {
  smoothedNx: number;
  smoothedNy: number;
  pendingDir: GazeDirection;
  pendingCount: number;
  stableDir: GazeDirection;
};

export function createInitialGazeState(): GazeStabilityState {
  return {
    smoothedNx: 0,
    smoothedNy: 0,
    pendingDir: "center",
    pendingCount: 0,
    stableDir: "center",
  };
}

function smooth(prev: number, next: number, alpha: number): number {
  return prev + alpha * (next - prev);
}

/**
 * nx, ny : position normalisée du centre du visage (−1..1 par axe).
 */
export function inferGazeFromSmoothedNorm(
  nx: number,
  ny: number,
  faceAreaRatio: number,
): GazeDirection {
  if (faceAreaRatio < MIN_FACE_AREA) return "off";
  if (nx * nx + ny * ny < DEAD_ZONE * DEAD_ZONE) return "center";
  const absX = Math.abs(nx);
  const absY = Math.abs(ny);
  if (absX >= absY) {
    if (nx < -THR_X) return "left";
    if (nx > THR_X) return "right";
  } else {
    if (ny < -THR_Y_UP) return "up";
    if (ny > THR_Y_DOWN) return "down";
  }
  return "center";
}

export function bboxToNorm(
  video: HTMLVideoElement,
  box: DOMRectReadOnly,
): { nx: number; ny: number; areaRatio: number } {
  const w = video.videoWidth || video.clientWidth || 1;
  const h = video.videoHeight || video.clientHeight || 1;
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  const nx = (cx - w / 2) / (w / 2);
  const ny = (cy - h / 2) / (h / 2);
  const areaRatio = (box.width * box.height) / (w * h);
  return { nx, ny, areaRatio };
}

/**
 * Met à jour le lissage + la direction stable (hystérésis par répétition).
 */
export function updateStableGaze(
  state: GazeStabilityState,
  nxRaw: number,
  nyRaw: number,
  areaRatio: number,
): { nextState: GazeStabilityState; direction: GazeDirection; confidence: number } {
  const sx = smooth(state.smoothedNx, nxRaw, SMOOTH_ALPHA);
  const sy = smooth(state.smoothedNy, nyRaw, SMOOTH_ALPHA);
  const rawDir = inferGazeFromSmoothedNorm(sx, sy, areaRatio);

  let pendingDir = state.pendingDir;
  let pendingCount = state.pendingCount;
  let stableDir = state.stableDir;

  if (rawDir === pendingDir) {
    pendingCount += 1;
  } else {
    pendingDir = rawDir;
    pendingCount = 1;
  }
  if (pendingCount >= GAZE_STABLE_FRAMES) {
    stableDir = pendingDir;
  }

  const nextState: GazeStabilityState = {
    smoothedNx: sx,
    smoothedNy: sy,
    pendingDir,
    pendingCount,
    stableDir,
  };

  const dist = Math.sqrt(sx * sx + sy * sy);
  const confidence = Math.max(0, Math.min(1, 1 - dist * 0.82));

  return { nextState, direction: stableDir, confidence };
}
