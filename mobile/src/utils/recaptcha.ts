declare global {
  interface Window {
    grecaptcha?: {
      ready(cb: () => void): void;
      execute(siteKey: string, options: { action: string }): Promise<string>;
    };
  }
}

const SITE_KEY = (import.meta as unknown as { env: Record<string, string> }).env
  .VITE_RECAPTCHA_SITE_KEY ?? '';

let _scriptPromise: Promise<void> | null = null;

function _loadScript(): Promise<void> {
  if (!SITE_KEY) return Promise.resolve();
  if (_scriptPromise) return _scriptPromise;
  _scriptPromise = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = `https://www.google.com/recaptcha/api.js?render=${SITE_KEY}`;
    script.onload = () => resolve();
    script.onerror = () => resolve(); // fail silently — backend will see empty token → bypass
    document.head.appendChild(script);
  });
  return _scriptPromise;
}

// Do NOT call _loadScript() here — loading is deferred to when LoginScreen
// or RegisterScreen mounts, so the reCAPTCHA badge never appears in the main app.
export function loadRecaptchaScript(): Promise<void> {
  return _loadScript();
}

export async function getRecaptchaToken(action: string): Promise<string> {
  if (!SITE_KEY) return '';
  await _loadScript();
  return new Promise((resolve) => {
    if (!window.grecaptcha) { resolve(''); return; }
    window.grecaptcha.ready(() => {
      window.grecaptcha!
        .execute(SITE_KEY, { action })
        .then(resolve)
        .catch(() => resolve(''));
    });
  });
}
