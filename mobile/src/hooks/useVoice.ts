import { useState, useRef } from 'react';

export function useVoice() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const startRecording = async (): Promise<void> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        // TODO: send to /audio/transcribe and set transcript
        setTranscript('');
      };

      recorder.start();
      setIsRecording(true);
    } catch {
      // TODO: handle permission error
    }
  };

  const stopRecording = (): void => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  return { isRecording, transcript, startRecording, stopRecording };
}
