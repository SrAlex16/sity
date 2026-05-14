export type PersonalitySettings = {
  sarcasm_level: number;
  rudeness_level: number;
  warmth_level: number;
  honesty_level: number;
  autonomy_level: number;
  proactivity_level: number;
  glados_mode: number;
  tsundere_level: number;
  patience_level: number;
  refusal_chance: number;
  helpfulness_level: number;
  verbosity_level: number;
};

export type PersonalityAdjustResponse = {
  ok: boolean;
  parameter: string;
  old_value: number;
  new_value: number;
  message: string;
};

const API_BASE = import.meta.env.VITE_SITY_API_BASE ?? "http://localhost:8000";

export async function getPersonality(): Promise<PersonalitySettings> {
  const response = await fetch(`${API_BASE}/settings/personality`);

  if (!response.ok) {
    throw new Error(`Failed to load personality: ${response.status}`);
  }

  return response.json();
}

export async function adjustPersonality(
  parameter: keyof PersonalitySettings,
  operation:
    | "increase_relative"
    | "decrease_relative"
    | "increase_absolute"
    | "decrease_absolute"
    | "set_absolute",
  amount: number,
): Promise<PersonalityAdjustResponse> {
  const response = await fetch(`${API_BASE}/settings/personality/adjust`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      parameter,
      operation,
      amount,
      source: "frontend",
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to adjust personality: ${response.status}`);
  }

  return response.json();
}
