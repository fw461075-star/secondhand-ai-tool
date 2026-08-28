// Service Worker - PWA离线缓存
// 版本号每次更新会强制清理旧缓存
const CACHE_NAME = 'secondhand-v3';
const CACHE_FILES = [
  '/',
  '/messages/labeled/review.html',
  '/manifest.json',
  '/messages/labeled/icon-192.png',
  '/messages/labeled/icon-512.png',
];

// 安装时缓存核心文件
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(CACHE_FILES).catch(() => {});
    })
  );
  self.skipWaiting();
});

// 激活时清理所有旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      // 删除所有不是当前版本的缓存
      return Promise.all(
        cacheNames.filter((name) => name !== CACHE_NAME).map((name) => {
          console.log('删除旧缓存:', name);
          return caches.delete(name);
        })
      );
    }).then(() => {
      // 强制控制所有客户端
      return self.clients.claim();
    })
  );
});

// 网络优先策略
self.addEventListener('fetch', (event) => {
  // 只处理GET请求
  if (event.request.method !== 'GET') return;
  
  // API请求不缓存
  if (event.request.url.includes('/api/')) return;
  
  // 图片请求：直接走网络，不缓存（避免缓存错误的404）
  if (event.request.url.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i)) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return caches.match(event.request);
      })
    );
    return;
  }
  
  // 其他资源：网络优先，失败时用缓存
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 只缓存成功的响应
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, clone).catch(() => {});
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          return cached || caches.match('/');
        });
      })
  );
});
