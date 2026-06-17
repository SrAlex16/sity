import { useEffect, useRef, useState } from "react";
import {
  getCurrentChat,
  sendChatMessage,
  type ChatArtifact,
  type ChatMessageResponse,
  API_BASE,
} from "../api/chatApi";

/** Logs only in development builds; compiled out in production. */
const debugLog = (...args: unknown[]): void => {
  if (import.meta.env.DEV) console.log(...args);
};

export type ChatEntry = {
  role: "user" | "sity";
  text: string;
  meta?: ChatMessageResponse;
  artifacts?: ChatArtifact[];
  created_at?: string;
};

function createClientTurnId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `turn_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export interface UseChatOptions {
  /** Called after a successful AI response — use to refresh personality / debug. */
  onMessageSent?: () => void;
}

export function useChat(options?: UseChatOptions) {
  const [chatInput, setChatInput] = useState("");
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([
    {
      role: "sity",
      text: "Estoy despierta. No prometo que eso mejore tus decisiones.",
    },
  ]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [pendingStatus, setPendingStatus] = useState<string | null>(null);
  const [activeClientTurnId, setActiveClientTurnId] = useState<string | null>(null);
  const [canCancel, setCanCancel] = useState(false);

  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  /** Holds the active EventSource so it can be closed on unmount. */
  const eventSourceRef = useRef<EventSource | null>(null);
  /** AbortController for the active sendChatMessage fetch. */
  const abortControllerRef = useRef<AbortController | null>(null);
  /** Original voice transcript before user edits; cleared on submit. */
  const voiceOriginalRef = useRef<string | null>(null);

  function scrollChatToBottom(behavior: ScrollBehavior = "smooth") {
    window.setTimeout(() => {
      chatBottomRef.current?.scrollIntoView({ behavior });
    }, 0);
  }

  async function loadCurrentChat() {
    try {
      const response = await getCurrentChat();
      if (response.messages.length > 0) {
        setChatEntries(
          response.messages.map((message) => ({
            role: message.role as "user" | "sity",
            text: message.text,
            created_at: message.created_at,
          })),
        );
        window.setTimeout(() => scrollChatToBottom("auto"), 50);
      }
    } catch {
      // Keep local default greeting if loading fails.
    }
  }

  async function cancelActiveOperation() {
    if (!activeClientTurnId) return;
    setCanCancel(false);
    setPendingStatus("Cancelando…");
    // Abort the in-flight fetch first, then notify the backend.
    abortControllerRef.current?.abort();
    await fetch(`${API_BASE}/events/chat/${activeClientTurnId}/cancel`, { method: "POST" });
  }

  function setVoiceTranscript(text: string, original: string) {
    setChatInput(text);
    voiceOriginalRef.current = original;
  }

  async function submitChat() {
    debugLog("[Sity submit] called", { chatInput, chatLoading });

    const trimmed = chatInput.trim();

    if (!trimmed || chatLoading) {
      debugLog("[Sity submit] blocked", { trimmed, chatLoading });
      return;
    }

    const voiceOriginal = voiceOriginalRef.current;
    voiceOriginalRef.current = null;

    const clientTurnId = createClientTurnId();
    debugLog("[Sity submit] clientTurnId", clientTurnId);

    setChatInput("");
    setChatError(null);
    setChatLoading(true);
    setCanCancel(false);
    setPendingStatus("Sity está trabajando…");
    setActiveClientTurnId(clientTurnId);
    setChatEntries((current) => [...current, { role: "user", text: trimmed, created_at: new Date().toISOString() }]);
    window.setTimeout(() => scrollChatToBottom("smooth"), 50);

    const eventSource = new EventSource(`${API_BASE}/events/chat/${clientTurnId}`);
    eventSourceRef.current = eventSource;
    debugLog("[Sity submit] EventSource opened");

    eventSource.onopen = () => {
      debugLog("[Sity SSE] open", clientTurnId);
    };

    eventSource.onmessage = (e) => {
      debugLog("[Sity SSE] message raw", e.data);
      const data = JSON.parse(e.data) as {
        type: string;
        label?: string;
        can_cancel?: boolean;
      };
      debugLog("[Sity SSE] message parsed", data);
      if (data.type === "tool_started") {
        setPendingStatus(data.label ?? "Trabajando…");
        setCanCancel(Boolean(data.can_cancel));
      }
      if (data.type === "tool_finished") {
        setCanCancel(false);
        setPendingStatus("Procesando respuesta…");
      }
      if (data.type === "cancelled") {
        setPendingStatus(data.label ?? "Cancelado.");
        setCanCancel(false);
      }
      if (data.type === "done" || data.type === "error") {
        setCanCancel(false);
        setActiveClientTurnId(null);
        eventSource.close();
      }
    };

    eventSource.onerror = (error) => {
      if (import.meta.env.DEV) console.error("[Sity SSE] error", error);
    };

    abortControllerRef.current = new AbortController();

    try {
      debugLog("[Sity submit] sending chat message");
      const response = await sendChatMessage(trimmed, clientTurnId, {
        signal: abortControllerRef.current.signal,
        ...(voiceOriginal != null
          ? { inputMode: "voice", voiceTranscriptOriginal: voiceOriginal }
          : {}),
      });
      debugLog("[Sity submit] response", response);

      setChatEntries((current) => [
        ...current,
        {
          role: "sity",
          text: response.text || "(sin respuesta)",
          meta: response,
          artifacts: response.artifacts ?? [],
          created_at: new Date().toISOString(),
        },
      ]);
      window.setTimeout(() => scrollChatToBottom("smooth"), 50);

      options?.onMessageSent?.();
    } catch (err) {
      // User-initiated cancel: swallow silently, no error message in chat.
      if (err instanceof DOMException && err.name === "AbortError") {
        debugLog("[Sity submit] aborted by user");
        return;
      }
      const errorMessage = err instanceof Error ? err.message : "Error desconocido";
      setChatError(errorMessage);
      setChatEntries((current) => [
        ...current,
        {
          role: "sity",
          text: `No he podido responder. ${errorMessage}`,
        },
      ]);
    } finally {
      debugLog("[Sity submit] finally cleanup");
      eventSource.close();
      eventSourceRef.current = null;
      abortControllerRef.current = null;
      setPendingStatus(null);
      setCanCancel(false);
      setActiveClientTurnId(null);
      setChatLoading(false);
    }
  }

  // Load persisted chat on mount.
  useEffect(() => {
    loadCurrentChat();
  }, []);

  // Scroll to bottom whenever entries or loading state changes.
  useEffect(() => {
    scrollChatToBottom("smooth");
  }, [chatEntries, chatLoading]);

  // On unmount: close any active EventSource and abort any in-flight fetch.
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      abortControllerRef.current?.abort();
    };
  }, []);

  return {
    chatInput,
    setChatInput,
    chatEntries,
    chatLoading,
    chatError,
    pendingStatus,
    activeClientTurnId,
    canCancel,
    chatBottomRef,
    scrollChatToBottom,
    submitChat,
    cancelActiveOperation,
    setVoiceTranscript,
  };
}
