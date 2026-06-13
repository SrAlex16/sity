import { useRef, useState } from "react";
import { transcribeAudio } from "../api/chatApi";

export interface UseVoiceInputOptions {
  onTranscript: (text: string, original: string) => void;
}

export interface UseVoiceInputResult {
  isRecording: boolean;
  isTranscribing: boolean;
  recordingError: string | null;
  toggleRecording: () => void;
}

export function useVoiceInput({ onTranscript }: UseVoiceInputOptions): UseVoiceInputResult {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [recordingError, setRecordingError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function startRecording() {
    setRecordingError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      chunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, {
          type: mediaRecorder.mimeType || "audio/webm",
        });
        chunksRef.current = [];
        if (blob.size === 0) return;
        setIsTranscribing(true);
        try {
          const result = await transcribeAudio(blob);
          if (result.transcript.trim()) {
            onTranscript(result.transcript, result.transcript);
          }
        } catch (err) {
          setRecordingError(err instanceof Error ? err.message : "Error al transcribir");
        } finally {
          setIsTranscribing(false);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      setRecordingError(
        err instanceof Error ? err.message : "Error al acceder al micrófono",
      );
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    mediaRecorderRef.current = null;
    setIsRecording(false);
  }

  function toggleRecording() {
    if (isRecording) {
      stopRecording();
    } else {
      void startRecording();
    }
  }

  return { isRecording, isTranscribing, recordingError, toggleRecording };
}
