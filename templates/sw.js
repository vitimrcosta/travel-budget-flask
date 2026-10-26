const CACHE_NAME = "rota-static-{{ version }}";
const OFFLINE_URL = "{{ url_for('offline_page') }}";
const PRECACHE = [
  OFFLINE_URL,
  "{{ url_for('static', filename='app.css') }}",
  "{{ url_for('static', filename='app.js') }}",
  "{{ url_for('static', filename='icons/icon-192.png') }}",
  "{{ url_for('static', filename='icons/icon-512.png') }}"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // Páginas com dados da viagem nunca são guardadas em cache.
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});
