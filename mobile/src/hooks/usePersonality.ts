import { useState, useEffect } from 'react';

export interface PersonalitySettings {
  warmth:              number;
  empathy:             number;
  directness:          number;
  assertiveness:       number;
  independence:        number;
  skepticism:          number;
  patience:            number;
  curiosity:           number;
  proactivity:         number;
  helpfulness:         number;
  honesty:             number;
  playfulness:         number;
  emotional_stability: number;
}

export function usePersonality() {
  const [settings, setSettings] = useState<PersonalitySettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    void load();
    const handler = () => void load();
    window.addEventListener('sity:personality-updated', handler);
    return () => window.removeEventListener('sity:personality-updated', handler);
  }, []);

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
      void load();
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
