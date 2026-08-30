import React, { useState, useEffect, useRef, useCallback } from 'react';

export type ChatStatus = 'conectado' | 'procesando' | 'desconectado';

const SESSION_ID = 'default';
const BG_FLASH_MS = 2000;

// ── Message types ─────────────────────────────────────────────────────────────

interface BaseMsg {
  id: string;
  role: 'user' | 'assistant';
  timestamp: Date;
  isError?: boolean;
  isCancelled?: boolean;
  trace_id?: string;
}

export interface TextChatMessage extends BaseMsg {
  type: 'text';
  text: string;
  imagePreviewUrl?: string; // data URL de la imagen adjunta (solo cliente, no persiste)
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
  audio_filename?: string;
  trace_id?: string;
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
  trace_id?: string;
  artifacts?: ApiArtifact[];
  personality_updated?: boolean;
}

interface ApiChatAccepted {
  turn_id: string;
  status: string;
}

interface SseEvent {
  type: string;
  data?: ApiChatResponse;
  label?: string;
  message?: string;
}

interface ApiTranscribeResponse {
  transcript: string;
  duration_ms: number;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChat(userKey: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>('desconectado');
  const [canCancel, setCanCancel] = useState(false);
  const [backgroundJobsActive, setBackgroundJobsActive] = useState(0);
  const [backgroundJustFinished, setBackgroundJustFinished] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentTurnIdRef = useRef<string | null>(null);
  const bgFlashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Always reflects the latest userKey so _listenTurn can validate events mid-flight.
  const userKeyRef = useRef<string | null>(userKey);
  userKeyRef.current = userKey;

  // On session change: clear all session-derived state before loading new history.
  // userKey === null means auth is still resolving — skip until identity is known.
  useEffect(() => {
    if (userKey === null) return;
    abortControllerRef.current?.abort();
    setMessages([]);
    setStatus('desconectado');
    setBackgroundJobsActive(0);
    setBackgroundJustFinished(false);
    setCanCancel(false);
    abortControllerRef.current = null;
    currentTurnIdRef.current = null;
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userKey]);

  // Persistent session SSE — receives background job notifications.
  // Re-subscribe when user identity changes so the new session's cookie is used.
  useEffect(() => {
    if (userKey === null) return;
    const es = new EventSource(`/events/session/${SESSION_ID}`);

    // Report tab visibility so the dispatcher can choose SSE-only vs SSE+push.
    // Called from es.onopen (not immediately) so the SSE queue exists on the
    // backend before the POST arrives — avoids a race where the POST is a no-op
    // because the queue hasn't been created yet and is_visible stays True.
    const reportVisibility = () => {
      fetch('/events/visibility', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_visible: document.visibilityState === 'visible' }),
      }).catch(() => undefined);
    };
    const onVisibilityChange = () => {
      reportVisibility();
      // When returning from background, reload history from DB so any proactive
      // messages delivered while the tab was frozen appear without a full F5.
      if (document.visibilityState === 'visible') void loadHistory();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    es.onmessage = (e: MessageEvent) => {
      let ev: { type: string; subtype?: string; job_id?: string; tool_name?: string; error?: string; text?: string };
      try { ev = JSON.parse(e.data as string); } catch { return; }

      if (ev.type === 'job_start') {
        setBackgroundJobsActive((n) => n + 1);
      } else if (ev.type === 'job_done' || ev.type === 'job_error') {
        setBackgroundJobsActive((n) => Math.max(0, n - 1));
        setBackgroundJustFinished(true);
        if (bgFlashTimerRef.current) clearTimeout(bgFlashTimerRef.current);
        bgFlashTimerRef.current = setTimeout(() => setBackgroundJustFinished(false), BG_FLASH_MS);
      } else if (ev.type === 'proactive_message' && ev.subtype === 'achievement_unlocked') {
        window.dispatchEvent(new CustomEvent('sity:achievement-unlocked'));
      } else if (ev.type === 'proactive_message' && ev.text) {
        setMessages((prev) => [...prev, {
          id: uid(), type: 'text' as const, role: 'assistant' as const,
          text: ev.text!, timestamp: new Date(),
        }]);
      }
    };

    // On (re)connect: report visibility now that the SSE queue exists on the backend,
    // and reload history after a drop so background results are visible immediately.
    let _reconnecting = false;
    es.onerror = () => { _reconnecting = true; };
    es.onopen = () => {
      reportVisibility();
      if (_reconnecting) { _reconnecting = false; void loadHistory(); }
    };

    return () => {
      es.close();
      document.removeEventListener('visibilitychange', reportVisibility);
      if (bgFlashTimerRef.current) clearTimeout(bgFlashTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userKey]);

  async function loadHistory() {
    try {
      const res = await fetch('/chat/current');
      if (!res.ok) throw new Error('network');
      const data = await res.json() as { messages: ApiHistoryMessage[] };

      const clearedAt = localStorage.getItem(`sity_chat_cleared_${userKey ?? 'unknown'}`);

      setMessages(
        data.messages
          .filter((m) => {
            if (!clearedAt) return true;
            if (!m.created_at) return true;
            return m.created_at > clearedAt;
          })
          .map((m): ChatMessage => {
            const ts = m.created_at ? new Date(m.created_at) : new Date();
            const role = m.role === 'user' ? 'user' : 'assistant';
            if (m.audio_filename && role === 'assistant') {
              return {
                id: uid(),
                type: 'audio',
                role,
                audioUrl: `/audio/stored/${m.audio_filename}`,
                transcript: m.text || undefined,
                timestamp: ts,
                trace_id: m.trace_id,
              };
            }
            return { id: uid(), type: 'text', role, text: m.text, timestamp: ts, trace_id: m.trace_id };
          }),
      );
      setStatus('conectado');
    } catch {
      setStatus('desconectado');
    }
  }

  async function sendMessage(
    text: string,
    images?: Array<{ mediaType: string; data: string; previewUrl: string }>,
  ) {
    // Block if a turn is already active — user must press Stop first.
    if (abortControllerRef.current) return;

    const trimmed = text.trim() || ' ';

    const userMsg: TextChatMessage = {
      id: uid(), type: 'text', role: 'user', text: trimmed, timestamp: new Date(),
      imagePreviewUrl: images?.[0]?.previewUrl,
    };
    setMessages((prev) => [...prev, userMsg]);
    setStatus('procesando');

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setCanCancel(true);

    try {
      // 1. POST → 202 immediately
      const res = await fetch('/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: trimmed,
          source_channel: 'mobile',
          images: images?.map((img) => ({ media_type: img.mediaType, data: img.data })) ?? [],
        }),
        signal: controller.signal,
      });
      if (res.status !== 202) throw new Error('network');
      const { turn_id } = await res.json() as ApiChatAccepted;
      currentTurnIdRef.current = turn_id;

      // 2. Subscribe to SSE — Cloudflare sees heartbeats and keeps the connection alive.
      await _listenTurn(turn_id, controller.signal, userKey, userKeyRef, setMessages, setStatus);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages((prev) => [...prev, cancelledMsg()]);
        setStatus('conectado');
      } else {
        setMessages((prev) => [...prev, errorMsg()]);
        setStatus('desconectado');
      }
    } finally {
      currentTurnIdRef.current = null;
      setCanCancel(false);
      abortControllerRef.current = null;
    }
  }

  /**
   * Transcribe audio → send as voice message.
   * Flow: /audio/transcribe → add user audio bubble → /chat/message (voice mode)
   */
  async function sendAudio(blob: Blob, durationSecs: number) {
    setStatus('procesando');

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setCanCancel(true);

    // 1. Transcribe
    const fd = new FormData();
    fd.append('file', blob, 'recording.webm');
    let transcript = '';
    let transcribedDuration = durationSecs;
    try {
      const res = await fetch('/audio/transcribe', { method: 'POST', body: fd, signal: controller.signal });
      if (!res.ok) throw new Error('transcribe failed');
      const data = await res.json() as ApiTranscribeResponse;
      transcript = data.transcript;
      if (data.duration_ms) transcribedDuration = data.duration_ms / 1000;
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setStatus('conectado');
      } else {
        setStatus('desconectado');
        setMessages((prev) => [...prev, errorMsg('No se pudo transcribir el audio.')]);
      }
      setCanCancel(false);
      abortControllerRef.current = null;
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
        signal: controller.signal,
      });
      if (res.status !== 202) throw new Error('network');
      const { turn_id } = await res.json() as ApiChatAccepted;
      currentTurnIdRef.current = turn_id;

      await _listenTurn(turn_id, controller.signal, userKey, userKeyRef, setMessages, setStatus);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages((prev) => [...prev, cancelledMsg()]);
        setStatus('conectado');
      } else {
        setMessages((prev) => [...prev, errorMsg()]);
        setStatus('desconectado');
      }
    } finally {
      currentTurnIdRef.current = null;
      setCanCancel(false);
      abortControllerRef.current = null;
    }
  }

  const cancel = useCallback(() => {
    const tid = currentTurnIdRef.current;
    if (tid) {
      fetch(`/chat/stream/${tid}/cancel`, { method: 'POST' }).catch(() => {});
    }
    abortControllerRef.current?.abort();
  }, []);

  function clearMessages() {
    // Key is scoped to userKey so that clearing as Guest never affects Admin's view.
    const key = `sity_chat_cleared_${userKey ?? 'unknown'}`;
    localStorage.setItem(key, new Date().toISOString());
    setMessages([]);
  }

  return { messages, status, sendMessage, sendAudio, clearMessages, canCancel, cancel, backgroundJobsActive, backgroundJustFinished };
}

export type UseChatResult = ReturnType<typeof useChat>;

// ── Private helpers ───────────────────────────────────────────────────────────

/**
 * Subscribe to /chat/stream/{turn_id} via EventSource and process events
 * until "done", "error", or "cancelled". Resolves when the turn is complete.
 * Heartbeat SSE comments (": heartbeat") are ignored by the browser automatically.
 */
function _listenTurn(
  turn_id: string,
  signal: AbortSignal,
  expectedUserKey: string | null,
  currentUserKeyRef: React.MutableRefObject<string | null>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setStatus: React.Dispatch<React.SetStateAction<ChatStatus>>,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/chat/stream/${turn_id}`);
    let serverClosedNormally = false;
    let responseSeen = false;

    es.onmessage = (e: MessageEvent) => {
      let ev: SseEvent;
      try {
        ev = JSON.parse(e.data as string) as SseEvent;
      } catch {
        return;
      }
      if (ev.type === 'response' && ev.data) {
        // Guard: discard if the session changed while this turn was in flight.
        // Covers the race where the response event was already queued before abort().
        if (currentUserKeyRef.current !== expectedUserKey) {
          es.close();
          resolve();
          return;
        }
        responseSeen = true;
        setMessages((prev) => [...prev, ...buildAssistantMessages(ev.data!)]);
        if (ev.data.personality_updated) {
          window.dispatchEvent(new CustomEvent('sity:personality-updated'));
        }
        setStatus('conectado');
      } else if (ev.type === 'done' || ev.type === 'cancelled') {
        serverClosedNormally = true;
        es.close();
        resolve();
      } else if (ev.type === 'error') {
        serverClosedNormally = true;
        es.close();
        reject(new Error(ev.label ?? 'Error del servidor'));
      }
    };

    es.onerror = () => {
      es.close();
      if (serverClosedNormally) {
        resolve();
      } else {
        reject(new Error('SSE connection error'));
      }
    };

    signal.addEventListener('abort', () => {
      es.close();
      if (!responseSeen && currentUserKeyRef.current === expectedUserKey) {
        setMessages((prev) => [...prev, cancelledMsg()]);
      }
      setStatus('conectado');
      resolve();
    }, { once: true });
  });
}

function buildAssistantMessages(data: ApiChatResponse): ChatMessage[] {
  const msgs: ChatMessage[] = [];
  const hasAudio = (data.artifacts ?? []).some((a) => a.type === 'audio');
  const traceId = data.trace_id;

  if (data.text && !hasAudio) {
    msgs.push({ id: uid(), type: 'text', role: 'assistant', text: data.text, timestamp: new Date(), trace_id: traceId });
  }

  let firstAudio = true;
  for (const artifact of data.artifacts ?? []) {
    if (artifact.type === 'audio') {
      msgs.push({
        id: uid(), type: 'audio', role: 'assistant',
        audioUrl: artifact.url, transcript: firstAudio ? (data.text || undefined) : undefined,
        timestamp: new Date(), trace_id: traceId,
      });
      firstAudio = false;
    }
  }

  if (msgs.length === 0) {
    msgs.push({ id: uid(), type: 'text', role: 'assistant', text: data.text ?? '', timestamp: new Date(), trace_id: traceId });
  }

  return msgs;
}

function errorMsg(text = 'Sin respuesta del servidor.'): TextChatMessage {
  return { id: uid(), type: 'text', role: 'assistant', text, timestamp: new Date(), isError: true };
}

function cancelledMsg(): TextChatMessage {
  return { id: uid(), type: 'text', role: 'assistant', text: '', isCancelled: true, timestamp: new Date() };
}
