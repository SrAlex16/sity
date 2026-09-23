import { useState, useEffect } from 'react';

export const GUEST_LANG_KEY = 'sity_lang_pref';

export const SUPPORTED_LANGUAGES = [
  { code: 'auto',   label: 'Auto (detecta el idioma)' },
  { code: 'es-ES',  label: 'Español (España)' },
  { code: 'es-419', label: 'Español (Latinoamérica)' },
  { code: 'en-US',  label: 'English (US)' },
  { code: 'en-GB',  label: 'English (UK)' },
  { code: 'ja',     label: '日本語' },
  { code: 'fr-FR',  label: 'Français' },
  { code: 'de-DE',  label: 'Deutsch' },
  { code: 'pt-BR',  label: 'Português (Brasil)' },
  { code: 'it-IT',  label: 'Italiano' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

export interface LanguageSettings {
  language_override: LanguageCode;
}

export function useLanguage(isGuest = false) {
  const [settings, setSettings] = useState<LanguageSettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isGuest) {
      const stored = sessionStorage.getItem(GUEST_LANG_KEY) as LanguageCode | null;
      setSettings({ language_override: stored ?? 'auto' });
      return;
    }
    void load();
  }, [isGuest]);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/language', { credentials: 'include' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as LanguageSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar');
    } finally {
      setIsLoading(false);
    }
  }

  async function save(code: LanguageCode) {
    if (isGuest) {
      if (code === 'auto') sessionStorage.removeItem(GUEST_LANG_KEY);
      else sessionStorage.setItem(GUEST_LANG_KEY, code);
      setSettings({ language_override: code });
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/settings/language', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ language_override: code }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSettings(await r.json() as LanguageSettings);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  return { settings, isLoading, error, save };
}
