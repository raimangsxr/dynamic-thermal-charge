/* Terminal calibration notifications must work without an open Angular tab. */
self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { payload = {}; }
  const session = payload.session_id ? ` (${payload.session_id})` : '';
  event.waitUntil(self.registration.showNotification('Calibración térmica finalizada', {
    body: `El resultado de la calibración está disponible en el panel${session}.`,
    tag: `thermal-calibration-${payload.session_id || 'terminal'}`,
    data: { url: '/calibracion' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/calibracion';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    const existing = clients.find((client) => 'focus' in client);
    if (existing) { existing.navigate(target); return existing.focus(); }
    return self.clients.openWindow(target);
  }));
});
