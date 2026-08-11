import { useState, useEffect } from 'react';
import type { UiLang } from '../i18n/translations';

const LS_KEY = 'sity_ui_lang';
const SUPPORTED: UiLang[] = ['es', 'en', 'ja'];

function isSupported(v: unknown): v is UiLang {
  return SUPPORTED.includes(v as UiLang);
}

export function useUiLanguage() {
  const [uiLang, _setUiLang] = useState<UiLang>(() => {
    const stored = localStorage.getItem(LS_KEY);
    return isSupported(stored) ? stored : 'es';
  });

  useEffect(() => {
    // Manual preference in localStorage always wins over geo suggestion
    if (localStorage.getItem(LS_KEY)) return;
    void (async () => {
      try {
        const r = await fetch('/settings/ui-language-suggestion');
        if (!r.ok) return;
        const { lang } = await r.json() as { lang: string };
        if (isSupported(lang)) _setUiLang(lang);
      } catch { /* silent — default stays */ }
    })();
  }, []);

  function setUiLang(lang: UiLang) {
    localStorage.setItem(LS_KEY, lang);
    _setUiLang(lang);
  }

  return { uiLang, setUiLang };
}
