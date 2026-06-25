import { useState, useEffect } from 'react';

export interface PersonalitySettings {
  sarcasm_level: number;
  rudeness_level: number;
  warmth_level: number;
  honesty_level: number;
  initiative_level: number;
  dry_humor_level: number;
  frialdad_afectiva_level: number;
  contrarian_level: number;
  patience_level: number;
  refusal_chance: number;
  helpfulness_level: number;
  verbosity_level: number;
  melancholy_level: number;
  skepticism_level: number;
}

export function usePersonality() {
  const [settings, setSettings] = useState<PersonalitySettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => { void load(); }, []);

  async function load() {
    setIsLoading(true);
    try {
      const res = await fetch('/settings/personality');
      if (!res.ok) throw new Error('fetch');
      setSettings(await res.json() as PersonalitySettings);
    } finally {
      setIsLoading(false);
    }
  }

  async function adjust(parameter: keyof PersonalitySettings, value: number) {
    // Optimistic update
    setSettings((prev) => prev ? { ...prev, [parameter]: value } : prev);
    try {
      const res = await fetch('/settings/personality/adjust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameter, operation: 'set_absolute', amount: value }),
      });
      if (!res.ok) throw new Error('adjust');
      const data = await res.json() as { new_value: number };
      setSettings((prev) => prev ? { ...prev, [parameter]: data.new_value } : prev);
    } catch {
      void load(); // revert via reload
    }
  }

  async function reset() {
    setIsLoading(true);
    try {
      const res = await fetch('/settings/personality/reset', { method: 'POST' });
      if (!res.ok) throw new Error('reset');
      setSettings(await res.json() as PersonalitySettings);
    } finally {
      setIsLoading(false);
    }
  }

  return { settings, isLoading, adjust, reset, reload: load };
}
