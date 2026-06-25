import { useState, useEffect } from 'react';

export type VoiceResponseMode = 'always' | 'never' | 'symmetric';
export type VoiceLongResponseAction = 'split' | 'text_only';

export interface VoiceSettings {
  voice_response_mode: VoiceResponseMode;
  voice_include_text: boolean;
  voice_long_response_action: VoiceLongResponseAction;
}

export const VOICE_DEFAULTS: VoiceSettings = {
  voice_response_mode: 'symmetric',
  voice_include_text: true,
  voice_long_response_action: 'text_only',
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
