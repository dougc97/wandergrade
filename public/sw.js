// WanderGrade service worker: installable PWA + offline shell.
//
// Strategy:
//  - Pages (navigations): network-first, falling back to the cached copy of
//    that page, then to the cached home shell when fully offline.
//  - Same-origin assets (js/css/geojson/api): stale-while-revalidate — serve
//    from cache instantly, refresh in the background. Assets are versioned
//    with ?v= query params, so new deploys naturally miss the cache.
//  - Cross-origin (fonts, Wikimedia photos, flag CDN): untouched; the browser
//    HTTP cache handles those.
// Bump CACHE on breaking changes to wipe old entries.
const CACHE = "wg-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(["/"])).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request).then((m) => m || caches.match("/")))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fresh = fetch(e.request)
        .then((r) => {
          if (r.ok) {
            const copy = r.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return r;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
