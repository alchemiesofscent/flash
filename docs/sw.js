const VERSION = 'v4';
const SHELL_CACHE = `flash-shell-${VERSION}`;
const DATA_CACHE = `flash-data-${VERSION}`;
const RUNTIME_CACHE = `flash-runtime-${VERSION}`;
const BASE_PATH = new URL('./', self.location).pathname.replace(/\/$/, '');

const APP_SHELL = [
  './',
  './index.html',
  './css/styles.css',
  './js/app.js',
  './js/data.js',
  './js/pwa.js',
  './js/questions.js',
  './js/state.js',
  './js/storage.js',
  './js/ui.js',
  './js/utils.js',
  './data/works.json',
  './manifest.json',
  './icons/apple-touch-icon.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
];

const SHELL_PATHS = new Set([
  '/index.html',
  '/css/styles.css',
  '/js/app.js',
  '/js/data.js',
  '/js/pwa.js',
  '/js/questions.js',
  '/js/state.js',
  '/js/storage.js',
  '/js/ui.js',
  '/js/utils.js',
  '/manifest.json',
  '/icons/apple-touch-icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
  '/data/works.json',
]);

function appUrl(path) {
  return new URL(path, self.location).toString();
}

function normalizePath(pathname) {
  if (BASE_PATH && BASE_PATH !== '/' && pathname.startsWith(BASE_PATH)) {
    return pathname.slice(BASE_PATH.length) || '/';
  }
  return pathname;
}

async function cacheShell() {
  const cache = await caches.open(SHELL_CACHE);
  await cache.addAll(APP_SHELL);
}

async function refreshCache(request, cacheName) {
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(cacheName);
    cache.put(request, response.clone());
  }
  return response;
}

async function cacheFirstRefresh(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const networkRefresh = refreshCache(request, cacheName).catch(() => null);
  if (cached) {
    return { response: cached, refresh: networkRefresh };
  }

  return { response: await networkRefresh || Response.error(), refresh: Promise.resolve(null) };
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const networkRefresh = refreshCache(request, cacheName).catch(() => cached);
  return { response: cached || await networkRefresh || Response.error(), refresh: networkRefresh };
}

async function warmWorkData() {
  const shellCache = await caches.open(SHELL_CACHE);
  const dataCache = await caches.open(DATA_CACHE);

  let worksResponse = await shellCache.match(appUrl('./data/works.json'));
  if (!worksResponse) {
    worksResponse = await refreshCache(appUrl('./data/works.json'), SHELL_CACHE);
  }
  if (!worksResponse) return;

  const works = await worksResponse.clone().json();
  await Promise.allSettled(
    works.map((work) => {
      const url = appUrl(`./data/${work.id}.json`);
      return refreshCache(url, DATA_CACHE).catch(async () => {
        await dataCache.match(url);
      });
    })
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    cacheShell().then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const validCaches = new Set([SHELL_CACHE, DATA_CACHE, RUNTIME_CACHE]);
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((key) => !validCaches.has(key))
        .map((key) => caches.delete(key))
    );
    await self.clients.claim();
    await warmWorkData();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);

  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(
      staleWhileRevalidate(event.request, RUNTIME_CACHE).then(({ response }) => response)
    );
    return;
  }

  if (url.origin !== self.location.origin) {
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        return await fetch(event.request);
      } catch (_err) {
        const cache = await caches.open(SHELL_CACHE);
        return cache.match(appUrl('./index.html')) || cache.match(appUrl('./')) || Response.error();
      }
    })());
    return;
  }

  const normalizedPath = normalizePath(url.pathname);

  if (/\/data\/[^/]+\.json$/.test(normalizedPath)) {
    const cacheName = url.pathname.endsWith('/works.json') ? SHELL_CACHE : DATA_CACHE;
    event.respondWith(
      cacheFirstRefresh(event.request, cacheName).then(({ response, refresh }) => {
        event.waitUntil(refresh);
        return response;
      })
    );
    return;
  }

  if (SHELL_PATHS.has(normalizedPath)) {
    event.respondWith(
      cacheFirstRefresh(event.request, SHELL_CACHE).then(({ response, refresh }) => {
        event.waitUntil(refresh);
        return response;
      })
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
