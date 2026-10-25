// Service Worker for AHIA Web Push Notifications
self.addEventListener("push", function (event) {
  if (!event.data) return;
  try {
    const data = event.data.json();
    const title = data.title || "AHIA Notification";
    const options = {
      body: data.body || "",
      icon: data.icon || "/icon-192.png",
      badge: "/icon-192.png",
      data: data.data || {},
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch {
    const text = event.data.text();
    event.waitUntil(
      self.registration.showNotification("AHIA", {
        body: text,
        icon: "/icon-192.png",
      })
    );
  }
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const urlToOpen = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if ("focus" in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
