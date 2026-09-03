import { useState, useEffect } from 'react';

export type VoiceResponseMode = 'always' | 'never' | 'symmetric';
export type VoiceLongResponseAction = 'split' | 'text_only';
export type TtsEngine = 'piper' | 'elevenlabs';

export type ModelUpgradeTtlHours = 2 | 4 | 6 | 8;

export interface VoiceSettings {
  voice_response_mode: VoiceResponseMode;
  voice_include_text: boolean;
  voice_long_response_action: VoiceLongResponseAction;
  audio_cleanup_days: number;
  tts_engine: TtsEngine;
  elevenlabs_chars_used: number;   // read-only from server
  elevenlabs_daily_limit: number;  // read-only from server
  model_upgrade_ttl_hours: ModelUpgradeTtlHours;
}

export const VOICE_DEFAULTS: VoiceSettings = {
  voice_response_mode: 'symmetric',
  voice_include_text: true,
  voice_long_response_action: 'text_only',
  audio_cleanup_days: 7,
  tts_engine: 'piper',
  elevenlabs_chars_used: 0,
  elevenlabs_daily_limit: 0,
  model_upgrade_ttl_hours: 4,
};

export function useVoice() {
  const [settings, setSettings] = useState<VoiceSettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void load(); }, []);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/voice');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as VoiceSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar');
    } finally {
      setIsLoading(false);
    }
  }

  async function save(next: VoiceSettings) {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/voice', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as VoiceSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  return { settings, isLoading, error, save, reload: load };
}
