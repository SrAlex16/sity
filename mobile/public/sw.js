self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
self.addEventListener('fetch', (event) => {
  // SSE connections must not be proxied through the SW — browser fetch()
  // inside a SW has an idle timeout (~3s) that kills long-lived streams.
  if (event.request.url.includes('/events/')) return;
  event.respondWith(fetch(event.request));
});
