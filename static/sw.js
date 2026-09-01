// Service Worker minimo para que la app sea instalable (PWA)
const CACHE = "monitoreo-v1";

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  self.clients.claim();
});

// Estrategia: siempre red primero (los datos deben ser en vivo)
self.addEventListener("fetch", (e) => {
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
