// 最小 Service Worker: アプリシェルをキャッシュ。
// 動画 (/library/*) と API はキャッシュしない (常に最新)。
const CACHE_VERSION = 'hls-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest',
               '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_VERSION).then((c) => c.addAll(SHELL)).catch(() => {}),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/library/') || url.pathname.startsWith('/api/')) {
    return; // ネットワーク直
  }
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request)),
  );
});
