import { useState, useEffect } from 'react';

export type LocationSource = 'manual' | 'browser' | 'auto' | 'denied' | '';

export interface LocationSettings {
  city: string;
  source: LocationSource;
}

export function useLocation() {
  const [settings, setSettings] = useState<LocationSettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void load(); }, []);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/location');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as LocationSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar');
    } finally {
      setIsLoading(false);
    }
  }

  async function save(next: LocationSettings) {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/location', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as LocationSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  return { settings, isLoading, error, save, reload: load };
}
