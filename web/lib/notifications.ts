/**
 * Web Push (VAPID) notification infrastructure for AHIA Web.
 *
 * Provides service worker registration, VAPID subscription, and token delivery
 * to the backend notification endpoint.
 */

import { API_BASE_URL } from "./api";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export function isPushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function getPushPermission(): NotificationPermission | "unsupported" {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission;
}

export async function getVapidPublicKey(tenantId: string): Promise<string> {
  const res = await fetch(
    `${API_BASE_URL}/api/v1/tenants/${tenantId}/notifications/vapid-public-key`,
    {
      credentials: "include",
    },
  );
  if (!res.ok) {
    throw new Error("Could not retrieve VAPID public key");
  }
  const data = (await res.json()) as { public_key: string };
  return data.public_key;
}

export async function registerPushSubscription(
  tenantId: string,
  subscription: PushSubscription,
): Promise<void> {
  const payload = subscription.toJSON();
  await fetch(`${API_BASE_URL}/api/v1/tenants/${tenantId}/notifications/push-subscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      subscription: payload,
      platform: "web",
    }),
  });
}

export async function subscribeToWebPush(
  tenantId: string,
): Promise<{ success: boolean; message: string }> {
  if (!isPushSupported()) {
    return { success: false, message: "Push notifications are not supported by this browser." };
  }

  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      return { success: false, message: "Notification permission was not granted." };
    }

    const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;

    const vapidKey = await getVapidPublicKey(tenantId);
    const convertedVapidKey = urlBase64ToUint8Array(vapidKey);

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: convertedVapidKey as unknown as BufferSource,
      });
    }

    await registerPushSubscription(tenantId, subscription);
    return { success: true, message: "Push notifications successfully enabled!" };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to subscribe to push notifications.";
    return { success: false, message };
  }
}
