// birdframe service worker — offline shell so the app opens even when the
// Mac is briefly unreachable. Live data still needs the server.
const CACHE = 'birdframe-v4';
const SHELL = ['/', '/icon-192.png', '/manifest.webmanifest',
  '/static/app.css?v=4', '/static/js/app.js?v=4'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Never cache live API calls — always go to the network.
  if (url.pathname.startsWith('/api/')) return;
  // Network-first for the shell, falling back to cache when offline.
  e.respondWith(
    fetch(e.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return resp;
    }).catch(() => caches.match(e.request).then(m => m || caches.match('/')))
  );
});
