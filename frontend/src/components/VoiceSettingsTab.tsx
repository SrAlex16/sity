import type { VoiceSettings, VoiceResponseMode, VoiceLongResponseAction } from "../api/voiceApi";

type VoiceSettingsTabProps = {
  settings: VoiceSettings | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  onChange: (next: VoiceSettings) => void;
};

const MODE_LABELS: Record<VoiceResponseMode, string> = {
  always: "Siempre",
  never: "Nunca",
  symmetric: "Simétrico (solo si el mensaje fue de voz)",
};

const LONG_ACTION_LABELS: Record<VoiceLongResponseAction, string> = {
  split: "Dividir en notas de voz",
  text_only: "Solo texto (sin audio)",
};

export function VoiceSettingsTab({ settings, loading, error, onReload, onChange }: VoiceSettingsTabProps) {
  if (loading) {
    return (
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-zinc-400">Cargando configuración de voz…</p>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Voz</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Respuestas de audio TTS con Piper.
          </p>
        </div>
        <button
          onClick={onReload}
          className="rounded-xl border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
        >
          Recargar
        </button>
      </div>

      {error && (
        <p className="rounded-xl bg-red-950 px-4 py-2 text-sm text-red-300">{error}</p>
      )}

      {settings && (
        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-2">
              Modo de respuesta de voz
            </label>
            <div className="space-y-2">
              {(["always", "never", "symmetric"] as VoiceResponseMode[]).map((mode) => (
                <label key={mode} className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="voice_response_mode"
                    value={mode}
                    checked={settings.voice_response_mode === mode}
                    onChange={() => onChange({ ...settings, voice_response_mode: mode })}
                    className="accent-cyan-400"
                  />
                  <span className="text-sm text-zinc-200">{MODE_LABELS[mode]}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={settings.voice_include_text}
                onChange={(e) => onChange({ ...settings, voice_include_text: e.target.checked })}
                className="accent-cyan-400 h-4 w-4"
              />
              <span className="text-sm text-zinc-200">
                Incluir transcripción de texto junto al audio
              </span>
            </label>
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-2">
              Respuestas largas
            </label>
            <div className="space-y-2">
              {(["split", "text_only"] as VoiceLongResponseAction[]).map((action) => (
                <label key={action} className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="voice_long_response_action"
                    value={action}
                    checked={settings.voice_long_response_action === action}
                    onChange={() => onChange({ ...settings, voice_long_response_action: action })}
                    className="accent-cyan-400"
                  />
                  <span className="text-sm text-zinc-200">{LONG_ACTION_LABELS[action]}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
