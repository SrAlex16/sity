import { useState, useEffect } from 'react';

export type ChatStatus = 'conectado' | 'procesando' | 'desconectado';

// ── Message types ─────────────────────────────────────────────────────────────

interface BaseMsg {
  id: string;
  role: 'user' | 'assistant';
  timestamp: Date;
  isError?: boolean;
}

export interface TextChatMessage extends BaseMsg {
  type: 'text';
  text: string;
}

export interface AudioChatMessage extends BaseMsg {
  type: 'audio';
  /** Local blob URL for user-recorded audio (ephemeral, lost on reload) */
  audioBlobUrl?: string;
  /** Server URL for assistant TTS artifact */
  audioUrl?: string;
  durationSecs?: number;
  /** STT transcript for user audio; TTS source text for assistant */
  transcript?: string;
}

export type ChatMessage = TextChatMessage | AudioChatMessage;

// ── Helpers ───────────────────────────────────────────────────────────────────

function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

interface ApiHistoryMessage {
  role: string;
  text: string;
  created_at?: string;
}

interface ApiArtifact {
  type: string;
  url: string;
  filename: string;
  mime_type?: string;
}

interface ApiChatResponse {
  ok: boolean;
  text: string;
  artifacts?: ApiArtifact[];
}

interface ApiTranscribeResponse {
  transcript: string;
  duration_ms: number;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>('desconectado');

  useEffect(() => { void loadHistory(); }, []);

  async function loadHistory() {
    try {
      const res = await fetch('/chat/current');
      if (!res.ok) throw new Error('network');
      const data = await res.json() as { messages: ApiHistoryMessage[] };

      const clearedRaw = localStorage.getItem('sity_chat_cleared');
      const clearedMs = clearedRaw ? Number(clearedRaw) : 0;

      setMessages(
        data.messages
          .filter((m) => {
            if (!clearedMs) return true;
            if (!m.created_at) return true;
            return new Date(m.created_at).getTime() >= clearedMs;
          })
          .map((m) => ({
            id: uid(),
            type: 'text' as const,
            role: m.role === 'user' ? 'user' : 'assistant',
            text: m.text,
            timestamp: m.created_at ? new Date(m.created_at) : new Date(),
          })),
      );
      setStatus('conectado');
    } catch {
      setStatus('desconectado');
    }
  }

  async function sendMessage(text: string) {
    const userMsg: TextChatMessage = { id: uid(), type: 'text', role: 'user', text, timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setStatus('procesando');

    try {
      const res = await fetch('/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, source_channel: 'mobile' }),
      });
      if (!res.ok) throw new Error('network');
      const data = await res.json() as ApiChatResponse;
      setMessages((prev) => [...prev, ...buildAssistantMessages(data)]);
      setStatus('conectado');
    } catch {
      setMessages((prev) => [...prev, errorMsg()]);
      setStatus('desconectado');
    }
  }

  /**
   * Transcribe audio → send as voice message.
   * Flow: /audio/transcribe → add user audio bubble → /chat/message (voice mode)
   */
  async function sendAudio(blob: Blob, durationSecs: number) {
    setStatus('procesando');

    // 1. Transcribe
    const fd = new FormData();
    fd.append('file', blob, 'recording.webm');
    let transcript = '';
    let transcribedDuration = durationSecs;
    try {
      const res = await fetch('/audio/transcribe', { method: 'POST', body: fd });
      if (!res.ok) throw new Error('transcribe failed');
      const data = await res.json() as ApiTranscribeResponse;
      transcript = data.transcript;
      if (data.duration_ms) transcribedDuration = data.duration_ms / 1000;
    } catch {
      setStatus('desconectado');
      setMessages((prev) => [...prev, errorMsg('No se pudo transcribir el audio.')]);
      return;
    }

    // 2. Add user audio message
    const audioBlobUrl = URL.createObjectURL(blob);
    const userMsg: AudioChatMessage = {
      id: uid(), type: 'audio', role: 'user',
      audioBlobUrl, durationSecs: transcribedDuration, transcript,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // 3. Send to chat as voice
    try {
      const res = await fetch('/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: transcript,
          input_mode: 'voice',
          voice_transcript_original: transcript,
          source_channel: 'mobile',
        }),
      });
      if (!res.ok) throw new Error('network');
      const data = await res.json() as ApiChatResponse;
      setMessages((prev) => [...prev, ...buildAssistantMessages(data)]);
      setStatus('conectado');
    } catch {
      setMessages((prev) => [...prev, errorMsg()]);
      setStatus('desconectado');
    }
  }

  function clearMessages() {
    setMessages([]);
    localStorage.setItem('sity_chat_cleared', Date.now().toString());
  }

  return { messages, status, sendMessage, sendAudio, clearMessages };
}

export type UseChatResult = ReturnType<typeof useChat>;

// ── Private helpers ───────────────────────────────────────────────────────────

function buildAssistantMessages(data: ApiChatResponse): ChatMessage[] {
  const msgs: ChatMessage[] = [];

  if (data.text) {
    msgs.push({ id: uid(), type: 'text', role: 'assistant', text: data.text, timestamp: new Date() });
  }

  for (const artifact of data.artifacts ?? []) {
    if (artifact.type === 'audio') {
      msgs.push({
        id: uid(), type: 'audio', role: 'assistant',
        audioUrl: artifact.url, transcript: data.text || undefined,
        timestamp: new Date(),
      });
    }
  }

  if (msgs.length === 0) {
    msgs.push({ id: uid(), type: 'text', role: 'assistant', text: data.text ?? '', timestamp: new Date() });
  }

  return msgs;
}

function errorMsg(text = 'Sin respuesta del servidor.'): TextChatMessage {
  return { id: uid(), type: 'text', role: 'assistant', text, timestamp: new Date(), isError: true };
}
