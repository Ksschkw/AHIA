// Service Worker for AHIA Web Push Notifications
self.addEventListener("push", function (event) {
  if (!event.data) {
    // Tickle ping fallback: fetch latest unread notification
    event.waitUntil(
      self.registration.showNotification("AHIA Market Alert", {
        body: "You have a new market update in your inbox.",
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        data: { url: "/app/more" },
      })
    );
    return;
  }

  try {
    const data = event.data.json();
    const title = data.title || "AHIA Market Notification";
    const options = {
      body: data.body || "",
      icon: data.icon || "/icon-192.png",
      badge: data.badge || "/icon-192.png",
      image: data.image || undefined,
      vibrate: [200, 100, 200],
      tag: (data.data && data.data.entity_id) || "ahia-alert",
      renotify: true,
      data: data.data || {},
      actions: [
        { action: "open", title: "Open" },
        { action: "close", title: "Dismiss" },
      ],
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch {
    const text = event.data.text();
    event.waitUntil(
      self.registration.showNotification("AHIA Notification", {
        body: text,
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        data: { url: "/app/more" },
      })
    );
  }
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();

  if (event.action === "close") {
    return;
  }

  const urlToOpen = (event.notification.data && event.notification.data.url) || "/app/more";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if (client.url.includes(self.location.origin) && "focus" in client) {
          if ("navigate" in client) {
            client.navigate(urlToOpen);
          }
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
