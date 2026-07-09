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
