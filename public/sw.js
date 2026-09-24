// WanderGrade service worker: installable PWA + offline shell.
//
// Strategy:
//  - Pages (navigations): network-first, falling back to the cached copy of
//    that page, then to the cached home shell when fully offline. Keyed by
//    path (utm/fbclid variants are one page) and capped, so the cache doesn't
//    grow a copy per campaign link.
//  - ?v=-stamped assets (app.js, styles.css, ppp.json): cache-first — the stamp
//    changes every deploy, so a cached copy is never stale. Storing a new stamp
//    evicts the old ones for the same path.
//  - Every other same-origin file (data JSON, geojson, icons): network-first,
//    cache only as the offline fallback. The server gives data files a short
//    max-age on purpose; fetch() here still goes through the HTTP cache, so that
//    window is honoured instead of serving whatever the previous visit saw.
//  - Cross-origin (fonts, Wikimedia photos, flag CDN), /api/, Range requests
//    and audio: untouched; the browser handles those.
//  - Only complete 200 responses are ever stored — never an error page or a
//    partial (206) body.
// Bump VER on breaking changes to wipe old entries.
// v2: /api/ excluded from SW caching — old caches may hold personal
// responses (auth/me, geo), so the bump wipes them on activate.
// v3: split page/asset caches, pruning, no error pages, no music.mp3 (a full
// cached body answered the Range requests iOS audio makes).
const VER = "v3";
const PAGES = "wg-pages-" + VER;
const ASSETS = "wg-assets-" + VER;
const MAX_PAGES = 40;

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(PAGES).then((c) => c.addAll(["/"])).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== PAGES && k !== ASSETS)
                                      .map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// A response worth keeping: a whole, successful, same-origin body.
const storable = (r) => r && r.status === 200 && r.type === "basic";

// Oldest-first trim of the page cache; "/" is the offline shell, never evicted.
async function trimPages(c) {
  const keys = (await c.keys()).filter((k) => new URL(k.url).pathname !== "/");
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_PAGES)).map((k) => c.delete(k)));
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;

  // /api/ responses are never SW-cached. Two are personal and marked no-store
  // by the server (/api/auth/me — serving it stale meant "still signed in"
  // after sign-out — and /api/geo), and the rest carry their own freshness
  // rules; a cache layer that ignores Cache-Control has no business here.
  if (url.pathname.startsWith("/api/")) return;
  // Media streams by byte range; a cache holding the whole 200 body would
  // answer every Range request with the full file (iOS then refuses to play).
  if (req.headers.has("range") || /\.(mp3|m4a|ogg|wav|mp4|webm)$/i.test(url.pathname)) return;

  if (req.mode === "navigate") {
    const key = url.origin + url.pathname;
    e.respondWith(
      fetch(req)
        .then((r) => {
          if (storable(r)) {
            const copy = r.clone();
            e.waitUntil(caches.open(PAGES).then((c) => c.put(key, copy).then(() => trimPages(c))));
          }
          return r;
        })
        .catch(() => caches.match(key, { cacheName: PAGES })
          .then((m) => m || caches.match("/", { cacheName: PAGES })))
    );
    return;
  }

  if (url.searchParams.has("v")) {
    e.respondWith(
      caches.match(req, { cacheName: ASSETS }).then((cached) => cached || fetch(req).then((r) => {
        if (storable(r)) {
          const copy = r.clone();
          e.waitUntil(caches.open(ASSETS).then(async (c) => {
            await c.put(req, copy);
            // Last deploy's copy of the same file is dead weight now.
            const old = (await c.keys()).filter((k) =>
              new URL(k.url).pathname === url.pathname && k.url !== req.url);
            await Promise.all(old.map((k) => c.delete(k)));
          }));
        }
        return r;
      }))
    );
    return;
  }

  e.respondWith(
    fetch(req)
      .then((r) => {
        if (storable(r)) {
          const copy = r.clone();
          e.waitUntil(caches.open(ASSETS).then((c) => c.put(req, copy)));
        }
        return r;
      })
      .catch(() => caches.match(req, { cacheName: ASSETS })
        .then((m) => m || Response.error()))
  );
});
