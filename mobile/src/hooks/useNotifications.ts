/**
 * useNotifications — Web Push subscription management.
 *
 * Responsibilities:
 * - Detect browser support for PushManager + Notification API
 * - Expose subscribe() / unsubscribe() as explicit user-triggered actions
 * - Persist subscription state across sessions via localStorage
 * - Never auto-trigger; never activate for guests
 */
import { useState, useEffect } from 'react';

const LS_KEY = 'sity_push_subscribed';

function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const buffer = new ArrayBuffer(rawData.length);
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < rawData.length; i++) {
    bytes[i] = rawData.charCodeAt(i);
  }
  return bytes;
}

async function getVapidPublicKey(): Promise<string> {
  const res = await fetch('/notifications/vapid-public-key', { credentials: 'include' });
  if (!res.ok) throw new Error(`VAPID key unavailable (${res.status})`);
  const body = (await res.json()) as { public_key: string };
  return body.public_key;
}

async function getOrCreateRegistration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration('/');
  if (existing) return existing;
  return navigator.serviceWorker.register('/sw.js', { scope: '/' });
}

export type NotificationPermission = 'default' | 'granted' | 'denied';

export interface UseNotificationsResult {
  isSupported: boolean;
  permission: NotificationPermission;
  isSubscribed: boolean;
  isLoading: boolean;
  error: string | null;
  subscribe: () => Promise<void>;
  unsubscribe: () => Promise<void>;
}

export function useNotifications(isGuest: boolean): UseNotificationsResult {
  const isSupported =
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'serviceWorker' in navigator &&
    'PushManager' in window;

  const [permission, setPermission] = useState<NotificationPermission>(
    isSupported ? (Notification.permission as NotificationPermission) : 'denied',
  );
  const [isSubscribed, setIsSubscribed] = useState(
    () => localStorage.getItem(LS_KEY) === 'true',
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync permission state if it changes externally (e.g. user revokes in browser settings)
  useEffect(() => {
    if (!isSupported) return;
    setPermission(Notification.permission as NotificationPermission);
    // If permission was revoked externally, clear local subscription flag
    if (Notification.permission === 'denied' && localStorage.getItem(LS_KEY) === 'true') {
      localStorage.removeItem(LS_KEY);
      setIsSubscribed(false);
    }
  });

  async function subscribe(): Promise<void> {
    if (isGuest || !isSupported || isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      const vapidKey = await getVapidPublicKey();

      const granted = await Notification.requestPermission();
      setPermission(granted as NotificationPermission);
      if (granted !== 'granted') {
        setError('Permiso de notificaciones denegado por el navegador.');
        return;
      }

      const reg = await getOrCreateRegistration();
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      });

      const subJson = sub.toJSON() as {
        endpoint: string;
        keys?: { p256dh: string; auth: string };
      };

      const res = await fetch('/notifications/subscribe', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint: subJson.endpoint,
          p256dh: subJson.keys?.p256dh ?? '',
          auth: subJson.keys?.auth ?? '',
        }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `Error del servidor (${res.status})`);
      }

      localStorage.setItem(LS_KEY, 'true');
      setIsSubscribed(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }

  async function unsubscribe(): Promise<void> {
    if (isGuest || !isSupported || isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      // Unsubscribe at browser level
      const reg = await navigator.serviceWorker.getRegistration('/');
      if (reg) {
        const sub = await reg.pushManager.getSubscription();
        if (sub) await sub.unsubscribe();
      }

      // Inform backend (best-effort; ignore server errors)
      await fetch('/notifications/subscribe', {
        method: 'DELETE',
        credentials: 'include',
      }).catch(() => undefined);

      localStorage.removeItem(LS_KEY);
      setIsSubscribed(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }

  return {
    isSupported,
    permission,
    isSubscribed,
    isLoading,
    error,
    subscribe,
    unsubscribe,
  };
}
