import { forwardRef, useCallback, useEffect, useRef, useState } from "react";

type CameraPreviewProps = {
  className?: string;
  /** Appelé quand le flux caméra est actif et que la vidéo a des dimensions valides (ou false si erreur / arrêt). */
  onReadyChange?: (ready: boolean) => void;
};

function assignRef<T>(ref: React.Ref<T> | undefined, value: T | null) {
  if (!ref) return;
  if (typeof ref === "function") {
    ref(value);
  } else {
    (ref as React.MutableRefObject<T | null>).current = value;
  }
}

/**
 * Fusionne la ref parent (proctoring / FaceDetector) et déclenche l’accès caméra
 * uniquement lorsque le nœud `<video>` est réellement monté.
 *
 * Les métriques visage (bbox) pour le proctoring et le score `phone_posture_score`
 * sont calculées dans `useOralProctoring` à partir du flux — voir
 * `src/oral-interview/utils/phonePosture.ts` (même espace de coordonnées intrinsèques
 * que `FaceDetector`, cohérent avec `object-cover` sur la balise vidéo).
 */
const CameraPreview = forwardRef<HTMLVideoElement, CameraPreviewProps>(function CameraPreview(
  { className, onReadyChange },
  ref,
) {
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const setVideoRef = useCallback(
    (node: HTMLVideoElement | null) => {
      setVideoEl(node);
      assignRef(ref, node);
    },
    [ref],
  );

  useEffect(() => {
    if (!videoEl) return;

    /** Autoplay mobile / iOS : muted + playsinline obligatoires */
    videoEl.defaultMuted = true;
    videoEl.muted = true;
    videoEl.playsInline = true;
    videoEl.autoplay = true;
    videoEl.setAttribute("muted", "");
    videoEl.setAttribute("playsinline", "true");
    videoEl.setAttribute("webkit-playsinline", "true");

    let cancelled = false;
    setCameraError(null);
    onReadyChange?.(false);

    const stopStream = () => {
      const s = streamRef.current;
      if (s) {
        s.getTracks().forEach((t) => {
          t.stop();
          console.info("[CameraPreview] track stopped:", t.kind, t.label);
        });
        streamRef.current = null;
      }
      if (videoEl.srcObject) {
        videoEl.srcObject = null;
      }
    };

    const playVideo = async () => {
      try {
        await videoEl.play();
        console.info("[CameraPreview] video.play() resolved");
      } catch (e) {
        console.warn("[CameraPreview] video.play() failed (will retry on interaction):", e);
      }
    };

    const signalReadyIfFrame = () => {
      const w = videoEl.videoWidth;
      const h = videoEl.videoHeight;
      if (w > 16 && h > 16) {
        onReadyChange?.(true);
      }
    };

    const onLoadedMetadata = () => {
      console.info("[CameraPreview] VIDEO READY (loadedmetadata)", {
        videoWidth: videoEl.videoWidth,
        videoHeight: videoEl.videoHeight,
        readyState: videoEl.readyState,
      });
      console.log("[VIDEO] readyState:", videoEl.readyState);
      console.log("[VIDEO] dimensions:", videoEl.videoWidth, videoEl.videoHeight);
      signalReadyIfFrame();
      void playVideo();
    };

    const onCanPlay = () => {
      console.info("[CameraPreview] canplay");
      console.log("[VIDEO] readyState (canplay):", videoEl.readyState);
      console.log("[VIDEO] dimensions (canplay):", videoEl.videoWidth, videoEl.videoHeight);
      signalReadyIfFrame();
      void playVideo();
    };

    const startVideo = async () => {
      stopStream();

      const tryConstraintsList: MediaStreamConstraints[] = [
        {
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 24, max: 30 } },
          audio: false,
        },
        { video: { facingMode: "user" }, audio: false },
        { video: true, audio: false },
      ];

      let stream: MediaStream | null = null;
      let lastErr: unknown;

      for (const constraints of tryConstraintsList) {
        try {
          stream = await navigator.mediaDevices.getUserMedia(constraints);
          console.info("[CameraPreview] getUserMedia OK", {
            constraints,
            videoTracks: stream.getVideoTracks().length,
            labels: stream.getVideoTracks().map((t) => t.label),
          });
          break;
        } catch (e) {
          lastErr = e;
          console.warn("[CameraPreview] getUserMedia attempt failed:", constraints, e);
        }
      }

      if (cancelled || !stream) {
        if (!cancelled && lastErr) {
          console.error("[CameraPreview] all getUserMedia attempts failed:", lastErr);
          setCameraError(
            "Impossible d’accéder à la caméra. Vérifiez les permissions et qu’aucune autre application n’utilise la webcam.",
          );
          onReadyChange?.(false);
        }
        return;
      }

      streamRef.current = stream;
      videoEl.srcObject = stream;
      const vTracks = stream.getVideoTracks();
      console.info("[CameraPreview] STREAM STARTED", {
        videoTracks: vTracks.length,
        active: stream.active,
      });
      console.log("[CAMERA] stream active:", stream.active);
      console.log(
        "[CAMERA] tracks:",
        vTracks.map((t) => ({
          kind: t.kind,
          label: t.label,
          readyState: t.readyState,
          enabled: t.enabled,
          muted: t.muted,
        })),
      );

      videoEl.addEventListener("loadedmetadata", onLoadedMetadata);
      videoEl.addEventListener("canplay", onCanPlay);

      if (videoEl.readyState >= 1) {
        void playVideo();
      }
    };

    void startVideo();

    return () => {
      cancelled = true;
      videoEl.removeEventListener("loadedmetadata", onLoadedMetadata);
      videoEl.removeEventListener("canplay", onCanPlay);
      stopStream();
      onReadyChange?.(false);
    };
  }, [videoEl, onReadyChange]);

  return (
    <div className="relative flex h-full min-h-[200px] w-full min-w-0 flex-1 items-center justify-center bg-black">
      {cameraError ? (
        <div
          className="absolute inset-0 z-10 flex items-center justify-center bg-background/95 p-4 text-center text-sm font-medium text-destructive backdrop-blur-[1px]"
          role="alert"
        >
          {cameraError}
        </div>
      ) : null}
      <video
        ref={setVideoRef}
        autoPlay
        muted
        playsInline
        className={
          className ??
          "relative z-0 h-full min-h-[200px] w-full min-w-0 object-cover bg-black [transform:translateZ(0)]"
        }
      />
    </div>
  );
});

export default CameraPreview;
