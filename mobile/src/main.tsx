import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/theme.css';
import './styles/global.css';
import './styles/animations.css';
import App from './App';

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      // If a new SW is already waiting (e.g. from a previous deploy),
      // tell it to activate immediately.
      if (reg.waiting) {
        reg.waiting.postMessage('SKIP_WAITING');
      }
      // Watch for a new SW installing mid-session and push it through.
      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        newWorker?.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && reg.waiting) {
            reg.waiting.postMessage('SKIP_WAITING');
          }
        });
      });
      // Proactively check for a new version on every page load.
      reg.update();
    }).catch(() => {});

    // Reload when a new SW takes control so the latest bundle is served.
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      window.location.reload();
    });
  });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
