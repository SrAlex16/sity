export type ChatUsage = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  daily_used_tokens: number;
  daily_budget_tokens: number;
  daily_ratio: number;
};

export type ChatArtifact = {
  type: "image" | "audio" | "file";
  url: string;
  filename: string;
  mime_type?: string | null;
};

export type ChatMessageResponse = {
  ok: boolean;
  trace_id: string;
  text: string;
  provider: string;
  model: string;
  fallback_used: boolean;
  error_type: string | null;
  usage: ChatUsage;
  warnings: string[];
  personality_updated: boolean;
  updated_parameter: string | null;
  updated_parameters: string[];
  artifacts: ChatArtifact[];
};

export type ChatHistoryItem = {
  role: "user" | "sity";
  text: string;
  created_at?: string;
};

export const API_BASE = import.meta.env.VITE_SITY_API_BASE ?? "http://localhost:8000";

export type SendChatOptions = {
  signal?: AbortSignal;
  inputMode?: "text" | "voice";
  voiceTranscriptOriginal?: string | null;
};

export async function sendChatMessage(
  message: string,
  clientTurnId?: string,
  options?: SendChatOptions,
): Promise<ChatMessageResponse> {
  const body: Record<string, unknown> = { message, client_turn_id: clientTurnId };
  if (options?.inputMode === "voice") {
    body.input_mode = "voice";
    if (options.voiceTranscriptOriginal != null) {
      body.voice_transcript_original = options.voiceTranscriptOriginal;
    }
  }
  const response = await fetch(`${API_BASE}/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: options?.signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to send chat message: ${response.status}`);
  }

  return response.json();
}

export type TranscribeResponse = {
  transcript: string;
  duration_ms: number;
};

export async function transcribeAudio(blob: Blob): Promise<TranscribeResponse> {
  const formData = new FormData();
  formData.append("file", blob, "audio.ogg");
  const response = await fetch(`${API_BASE}/audio/transcribe`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error(`Transcription failed: ${response.status}`);
  }
  return response.json();
}

export type CurrentChatResponse = {
  ok: boolean;
  session_id: string;
  messages: ChatHistoryItem[];
};

export async function getCurrentChat(): Promise<CurrentChatResponse> {
  const response = await fetch(`${API_BASE}/chat/current`);

  if (!response.ok) {
    throw new Error(`Failed to load current chat: ${response.status}`);
  }

  return response.json();
}
