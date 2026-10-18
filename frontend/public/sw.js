// Minimal service worker: network-first for pages, cache fallback when offline.
// Full offline caching and push notifications come in step 11.
const CACHE = "showcase-v2";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(req)
      .then((res) => {
        // Never cache a URL with a query string (e.g. /welcome?prefill=<one-time token>).
        if (res.ok && !new URL(req.url).search &&
            (req.mode === "navigate" || req.destination === "script" || req.destination === "style")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || Response.error()))
  );
});
