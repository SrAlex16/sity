self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
self.addEventListener('fetch', (event) => {
  // SSE connections must not be proxied through the SW — browser fetch()
  // inside a SW has an idle timeout (~3s) that kills long-lived streams.
  if (event.request.url.includes('/events/')) return;
  event.respondWith(fetch(event.request));
});

self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title ?? 'Sity';
  const options = {
    body: data.body ?? '',
    icon: '/icons/sity_icon_192.png',
    badge: '/icons/sity_icon_192.png',
    data: { url: data.url ?? '/' },
    ...(data.urgent ? { vibrate: [200, 100, 200] } : {}),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url ?? '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const existing = list.find((c) => c.url.includes(targetUrl));
      if (existing) return existing.focus();
      return clients.openWindow(targetUrl);
    })
  );
});
