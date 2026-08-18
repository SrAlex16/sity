import { useState, useEffect } from 'react';

export interface InitiativeSettings {
  enabled: boolean;
  trigger_conversation_abandoned: boolean;
  trigger_long_inactivity: boolean;
  trigger_open_loop: boolean;
}

export const INITIATIVE_DEFAULTS: InitiativeSettings = {
  enabled: true,
  trigger_conversation_abandoned: true,
  trigger_long_inactivity: true,
  trigger_open_loop: true,
};

export function useInitiative() {
  const [settings, setSettings] = useState<InitiativeSettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void load(); }, []);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/initiative');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as InitiativeSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar');
    } finally {
      setIsLoading(false);
    }
  }

  async function save(next: InitiativeSettings) {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/initiative', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as InitiativeSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  return { settings, isLoading, error, save };
}
