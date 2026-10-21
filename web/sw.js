/* FishAutoPro Clone service worker: shell + last-known API data cache. */
const CACHE = 'fap-shell-v3';
const DATA_CACHE = 'fap-data-v1';
const ASSETS = [
  '/',
  '/styles.css',
  '/app.js',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];
const NO_DATA_CACHE = ['/api/auth/sessions', '/api/events/', '/api/exports/',
  '/api/backups/download', '/api/health', '/api/system/'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== DATA_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'clear-data') event.waitUntil(caches.delete(DATA_CACHE));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    if (NO_DATA_CACHE.some((p) => url.pathname.startsWith(p))) return;
    event.respondWith(
      fetch(event.request).then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(DATA_CACHE).then((cache) => cache.put(url.pathname, copy)).catch(() => {});
        }
        return resp;
      }).catch(() => caches.match(url.pathname))
    );
    return;
  }
  if (url.pathname.startsWith('/media/')) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/').then((cached) => cached || Response.error()))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).then((resp) => {
      const copy = resp.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => {});
      return resp;
    }).catch(() => caches.match('/')))
  );
});
