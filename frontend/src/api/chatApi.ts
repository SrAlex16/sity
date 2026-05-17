export type ChatUsage = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  daily_used_tokens: number;
  daily_budget_tokens: number;
  daily_ratio: number;
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
};

export type ChatHistoryItem = {
  role: "user" | "sity";
  text: string;
};

const API_BASE = import.meta.env.VITE_SITY_API_BASE ?? "http://localhost:8000";

export async function sendChatMessage(
  message: string,
): Promise<ChatMessageResponse> {
  const response = await fetch(`${API_BASE}/chat/message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    throw new Error(`Failed to send chat message: ${response.status}`);
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
