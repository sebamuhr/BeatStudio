/* Beatbox to MIDI — service worker (offline + installable PWA) */
const VERSION = 'beatbox-0.7.6';   // keep in sync with the <title> version in the app
const CORE = VERSION + '-core';
const RUNTIME = VERSION + '-runtime';

const APP_HTML = './Beatbox%20to%20MIDI.dc.html';
const CORE_ASSETS = [
  './',
  APP_HTML,
  './support.js',
  './vendor/react.production.min.js',
  './vendor/react-dom.production.min.js',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(CORE);
    // Add individually so one missing/optional file can't fail the whole install.
    await Promise.all(CORE_ASSETS.map((u) =>
      cache.add(new Request(u, { cache: 'reload' })).catch(() => {})
    ));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Sync API must always hit the network — never cache it, or the app would think
  // it's online when it isn't and show a stale groove list.
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) return;

  // App navigation: cache-first so it launches instantly offline (e.g. in the park),
  // then refresh the cached shell in the background when a network is available.
  if (req.mode === 'navigate') {
    e.respondWith((async () => {
      const cached = (await caches.match(APP_HTML)) || (await caches.match('./'));
      const network = fetch(req).then((fresh) => {
        caches.open(CORE).then((c) => c.put(APP_HTML, fresh.clone()));
        return fresh;
      }).catch(() => null);
      return cached || (await network) || Response.error();
    })());
    return;
  }

  // Google Fonts (cross-origin): cache-first, fill on demand.
  if (url.hostname.endsWith('googleapis.com') || url.hostname.endsWith('gstatic.com')) {
    e.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const res = await fetch(req);
        const cache = await caches.open(RUNTIME);
        cache.put(req, res.clone());
        return res;
      } catch (err) {
        return cached || Response.error();
      }
    })());
    return;
  }

  // Same-origin static assets: cache-first, refresh in background.
  if (url.origin === self.location.origin) {
    e.respondWith((async () => {
      const cached = await caches.match(req);
      const network = fetch(req).then((res) => {
        if (res && res.ok) caches.open(CORE).then((c) => c.put(req, res.clone()));
        return res;
      }).catch(() => null);
      return cached || (await network) || Response.error();
    })());
  }
});
