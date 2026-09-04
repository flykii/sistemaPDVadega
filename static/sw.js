/**
 * Service Worker do PDV Enterprise PWA
 * Estratégia de cache refinada:
 * - Recursos estáticos (CSS, JS, Fonts): Cache-First com atualização em background.
 * - Navegação HTML (Shell do PDV): Network-First com fallback para cache.
 * - Requisições de API (/api/*): Network-Only (NUNCA armazena dados transacionais em HTTP Cache).
 */

const CACHE_VERSION = 'pdv-enterprise-v2.1';
const STATIC_CACHE_NAME = `pdv-static-${CACHE_VERSION}`;

const STATIC_ASSETS = [
  '/',
  '/vendas/pdv/',
  '/static/css/custom.css',
  '/static/css/pdv.css',
  '/static/js/pdv-offline-db.js',
  '/static/js/pdv-app.js',
  '/static/manifest.json',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
  'https://unpkg.com/htmx.org@1.9.10',
  'https://cdn.jsdelivr.net/npm/chart.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[ServiceWorker] Aviso ao pré-carregar assets estáticos:', err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== STATIC_CACHE_NAME) {
            console.log('[ServiceWorker] Removendo cache legado:', key);
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. APIs e chamadas não-GET: NUNCA interceptadas pelo ServiceWorker Cache (Network-Only)
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    return;
  }

  // 2. Navegação de páginas HTML: Network-First com fallback de cache
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.status === 200) {
            const clone = response.clone();
            caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          if (cached) return cached;
          const fallbackPdv = await caches.match('/vendas/pdv/');
          if (fallbackPdv) return fallbackPdv;
          return caches.match('/');
        })
    );
    return;
  }

  // 3. Recursos Estáticos (CSS, JS, Imagens, Fontes): Cache-First
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        // Atualiza cache em segundo plano (Stale-While-Revalidate)
        fetch(event.request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
            }
          })
          .catch(() => {});
        return cachedResponse;
      }

      return fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const clone = networkResponse.clone();
          caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return networkResponse;
      });
    })
  );
});
