/*
 * Kadai service worker.
 *
 * The API is never cached here: customer and price data live in IndexedDB so
 * the salesman can read them offline, and the outbox owns order writes. This
 * worker only keeps the app shell available and relays a Background Sync
 * wake-up to the open page, which then flushes the outbox with its session
 * cookie and CSRF token.
 */
const PRECACHE = 'kadai-shell-v1'
const SHELL_MANIFEST = self.__WB_MANIFEST

self.addEventListener('install', (event) => {
  const urls = SHELL_MANIFEST.map((entry) => (typeof entry === 'string' ? entry : entry.url))
  event.waitUntil(
    caches
      .open(PRECACHE)
      .then((cache) => cache.addAll(urls))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== PRECACHE).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html')))
    return
  }

  event.respondWith(caches.match(request).then((cached) => cached || fetch(request)))
})

self.addEventListener('sync', (event) => {
  if (event.tag !== 'kadai-order-sync') return
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: 'kadai:sync-orders' }))
    })
  )
})
