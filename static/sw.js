/**
 * Service Worker do PDV Enterprise PWA
 * Estratégia de cache refinada:
 * - Recursos estáticos (CSS, JS, Fonts): Cache-First com atualização em background.
 * - Navegação HTML (Shell do PDV): Network-First com fallback para cache.
 * - Requisições de API (/api/*): Network-Only (NUNCA armazena dados transacionais em HTTP Cache).
 */

const CACHE_VERSION = 'pdv-enterprise-v2.3';
const STATIC_CACHE_NAME = `pdv-static-${CACHE_VERSION}`;

const STATIC_ASSETS = [
  '/',
  '/pdv/',
  '/vendas/pdv/',
  '/static/css/custom.css',
  '/static/css/custom.css?v=2.1',
  '/static/css/pdv.css',
  '/static/css/pdv.css?v=2.1',
  '/static/js/pdv-offline-db.js',
  '/static/js/pdv-offline-db.js?v=2.1',
  '/static/js/pdv-app.js',
  '/static/js/pdv-app.js?v=2.1',
  '/static/manifest.json',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
  'https://unpkg.com/htmx.org@1.9.10',
  'https://cdn.jsdelivr.net/npm/chart.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME).then(async (cache) => {
      // Promise.allSettled para NUNCA abortar a instalação se uma rota opcional falhar
      const results = await Promise.allSettled(
        STATIC_ASSETS.map((asset) => cache.add(asset))
      );
      results.forEach((res, i) => {
        if (res.status === 'rejected') {
          console.warn(`[ServiceWorker] Asset opcional não pré-carregado (${STATIC_ASSETS[i]}):`, res.reason);
        }
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

  // 1. APIs e chamadas não-GET: NUNCA interceptadas pelo ServiceWorker Cache (Network-Only direta)
  if (event.request.method !== 'GET' || url.pathname.includes('/api/')) {
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
          const fallbackPdvRoot = await caches.match('/pdv/');
          if (fallbackPdvRoot) return fallbackPdvRoot;
          return caches.match('/');
        })
    );
    return;
  }

  // 3. Arquivos JavaScript (.js): Network-First (busca sempre a versão mais nova do servidor)
  if (url.pathname.endsWith('.js') || url.pathname.includes('.js?')) {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const clone = networkResponse.clone();
            caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return networkResponse;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          if (cached) return cached;
          return new Response('// Offline JS fallback', { headers: { 'Content-Type': 'application/javascript' } });
        })
    );
    return;
  }

  // 4. Recursos Estáticos Gerais (CSS, Imagens, Fontes, CDNs): Cache-First com Stale-While-Revalidate
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
