/* 現場写真 PWA — Service Worker
   役割: アプリシェルをキャッシュし、現場でのオフライン起動を可能にする。
   方針:
     - アプリシェル（HTML/manifest/icon）はキャッシュ優先（cache-first）。
     - /api/ への通信は常にネットワーク（キャッシュしない）。
     - ナビゲーション要求はオフライン時にキャッシュ済みアプリへフォールバック。
   キャッシュ更新: CACHE_VERSION を上げると古いキャッシュを破棄する。
*/
const CACHE_VERSION = "genba-photo-v1";
const APP_SHELL = [
  "pwa-app.html",
  "manifest.json",
  "icon.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // GET以外、APIアクセスはキャッシュ介入しない
  if (req.method !== "GET" || url.pathname.includes("/api/")) {
    return; // 既定のネットワーク処理
  }

  // ナビゲーション（ページ遷移）: ネット優先、失敗時にアプリシェルへ
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("pwa-app.html"))
    );
    return;
  }

  // それ以外: キャッシュ優先、無ければネットワーク取得しキャッシュ
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        // 同一オリジンの正常応答のみキャッシュ
        if (res && res.status === 200 && url.origin === self.location.origin) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => cached);
    })
  );
});
