import { API_BASE } from "./chatApi";

export type VoiceResponseMode = "always" | "never" | "symmetric";
export type VoiceLongResponseAction = "split" | "text_only";

export type VoiceSettings = {
  voice_response_mode: VoiceResponseMode;
  voice_include_text: boolean;
  voice_long_response_action: VoiceLongResponseAction;
};

export async function getVoiceSettings(): Promise<VoiceSettings> {
  const r = await fetch(`${API_BASE}/settings/voice`);
  if (!r.ok) throw new Error(`Error ${r.status}`);
  return r.json();
}

export async function updateVoiceSettings(settings: VoiceSettings): Promise<VoiceSettings> {
  const r = await fetch(`${API_BASE}/settings/voice`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!r.ok) throw new Error(`Error ${r.status}`);
  return r.json();
}
