import { useState, useRef, useCallback } from "react";

export const useRecorder = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  /** Durée de l'enregistrement terminé (secondes), pour l'envoi API */
  const [lastDurationSeconds, setLastDurationSeconds] = useState<number | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const startedAtRef = useRef<number | null>(null);

  const startRecording = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];

    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: "audio/webm" });
      setAudioBlob(blob);
      if (startedAtRef.current != null) {
        const sec = Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000));
        setLastDurationSeconds(sec);
      } else {
        setLastDurationSeconds(null);
      }
      startedAtRef.current = null;
    };

    startedAtRef.current = Date.now();
    recorder.start();
    mediaRecorderRef.current = recorder;
    setIsRecording(true);
  }, []);

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
    mediaRecorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  /** Réinitialise l’état entre deux questions (évite toute réutilisation accidentelle du blob précédent). */
  const clearRecordingOutput = useCallback(() => {
    setAudioBlob(null);
    setLastDurationSeconds(null);
    startedAtRef.current = null;
  }, []);

  return {
    isRecording,
    startRecording,
    stopRecording,
    audioBlob,
    lastDurationSeconds,
    clearRecordingOutput,
  };
};
