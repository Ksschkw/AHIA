/**
 * Push notification & In-app notification infrastructure for AHIA Mobile.
 *
 * Provides safe device token registration and unread notification state management.
 */

import { isRunningInExpoGo } from "expo";
import Constants, { ExecutionEnvironment } from "expo-constants";
import { Platform } from "react-native";

import {
  getUnreadNotificationCount,
  getNotifications,
  markNotificationRead,
  request,
  type AppNotification,
} from "./api";

/**
 * Check if running inside Expo Go.
 * Uses official isRunningInExpoGo() from 'expo', with Constants fallback.
 */
export function isExpoGoClient(): boolean {
  try {
    if (isRunningInExpoGo()) return true;
  } catch {
    // ignore
  }
  return (
    Constants.appOwnership === "expo" ||
    Constants.executionEnvironment === ExecutionEnvironment.StoreClient
  );
}

/**
 * Expo Go on Android removed remote notification native modules (SDK 53+).
 * Safely load expo-notifications only when supported to prevent ExpoTopicSubscriptionModule crashes.
 */
function getNotificationsModule(): typeof import("expo-notifications") | null {
  if (Platform.OS === "android" && isExpoGoClient()) {
    return null;
  }
  try {
    return require("expo-notifications");
  } catch {
    return null;
  }
}

let handlerConfigured = false;
function ensureHandlerConfigured(notif: typeof import("expo-notifications")) {
  if (handlerConfigured) return;
  handlerConfigured = true;
  try {
    notif.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: true,
        shouldShowBanner: true,
        shouldShowList: true,
      }),
    });
  } catch {
    // Fallback if native handler setup fails
  }
}

/**
 * Configure Android notification channels with categorized priorities.
 */
export async function setupCategorizedChannelsAsync(
  notif: typeof import("expo-notifications"),
): Promise<void> {
  if (Platform.OS !== "android") return;
  try {
    await notif.setNotificationChannelAsync("orders", {
      name: "Orders & Waybills",
      description: "Alerts when customers send order lists or request waybills",
      importance: notif.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#084a2f",
      sound: "default",
      enableVibrate: true,
      showBadge: true,
    });
    await notif.setNotificationChannelAsync("payments", {
      name: "Payments & Receipts",
      description: "Alerts when customers upload payment proofs or settle sales",
      importance: notif.AndroidImportance.HIGH,
      vibrationPattern: [0, 200, 100, 200],
      lightColor: "#22c55e",
      sound: "default",
      enableVibrate: true,
      showBadge: true,
    });
    await notif.setNotificationChannelAsync("inventory", {
      name: "Stock & Restock Alerts",
      description: "Alerts when inventory runs low or needs replenishment",
      importance: notif.AndroidImportance.DEFAULT,
      lightColor: "#f59e0b",
      sound: "default",
      showBadge: true,
    });
    await notif.setNotificationChannelAsync("default", {
      name: "General Shop Alerts",
      description: "General shop notifications and activity",
      importance: notif.AndroidImportance.DEFAULT,
      lightColor: "#084a2f",
      sound: "default",
      showBadge: true,
    });
  } catch (err) {
    console.warn("setupCategorizedChannelsAsync error:", err);
  }
}

/**
 * Check if the device has granted notification permissions.
 */
export async function checkNotificationPermission(): Promise<boolean> {
  const notif = getNotificationsModule();
  if (!notif) return false;
  try {
    const { status } = await notif.getPermissionsAsync();
    return status === "granted";
  } catch {
    return false;
  }
}

/**
 * Fire an immediate local notification on the device.
 * Used for instant order delivery alerts and local testing without remote FCM reliance.
 */
export async function triggerLocalNotification(options: {
  title: string;
  body: string;
  channelId?: "orders" | "payments" | "inventory" | "default";
  data?: Record<string, unknown>;
}): Promise<boolean> {
  const notif = getNotificationsModule();
  if (!notif) return false;
  ensureHandlerConfigured(notif);
  try {
    await setupCategorizedChannelsAsync(notif);
    await notif.scheduleNotificationAsync({
      content: {
        title: options.title,
        body: options.body,
        data: options.data,
        sound: "default",
      },
      trigger: options.channelId
        ? ({ channelId: options.channelId } as never)
        : null,
    });
    return true;
  } catch (err) {
    console.warn("triggerLocalNotification error:", err);
    return false;
  }
}

export function isPushNotificationSupported(): boolean {
  if (Platform.OS === "android" && isExpoGoClient()) {
    return false;
  }
  return true;
}

export interface PushTokenPayload {
  token: string;
  platform: "android" | "ios";
  device_name?: string;
}

let activePushToken: string | null = null;

export function getActivePushToken(): string | null {
  return activePushToken;
}

export function setActivePushToken(token: string | null): void {
  activePushToken = token;
}

/**
 * Request notification permissions and register the Expo push token
 * across all businesses the user has access to.
 */
export async function registerForPushNotificationsAsync(
  tenantIds: string[],
): Promise<{ success: boolean; token?: string; error?: string; permissionGranted?: boolean }> {
  const notif = getNotificationsModule();
  if (!notif) {
    return {
      success: false,
      error: "Remote push notifications require a standalone APK/development build (unavailable in Expo Go on Android).",
    };
  }

  ensureHandlerConfigured(notif);

  try {
    if (Platform.OS === "android") {
      await setupCategorizedChannelsAsync(notif);
    }

    const { status: existingStatus } = await notif.getPermissionsAsync();
    let finalStatus = existingStatus;
    if (existingStatus !== "granted") {
      const { status } = await notif.requestPermissionsAsync();
      finalStatus = status;
    }
    if (finalStatus !== "granted") {
      return { success: false, error: "Notification permission not granted", permissionGranted: false };
    }

    const projectId =
      (Constants?.expoConfig?.extra?.eas?.projectId as string | undefined) ??
      (Constants?.easConfig?.projectId as string | undefined);

    let token: string | null = null;
    let tokenError: string | null = null;
    try {
      const tokenData = await notif.getExpoPushTokenAsync(
        projectId ? { projectId } : undefined,
      );
      if (tokenData?.data) {
        token = tokenData.data;
      }
    } catch (err: unknown) {
      tokenError = err instanceof Error ? err.message : String(err);
      console.warn("getExpoPushTokenAsync failed:", tokenError);
    }

    if (!token) {
      const isMissingFcm =
        !tokenError ||
        tokenError.includes("FirebaseApp") ||
        tokenError.includes("google-services") ||
        tokenError.includes("FIS_AUTH_ERROR") ||
        tokenError.includes("SERVICE_NOT_AVAILABLE");
      const userMessage = isMissingFcm
        ? "Device alerts active for orders. Remote push requires FCM google-services.json."
        : (tokenError ?? "Failed to generate push token");
      return { success: false, error: userMessage, permissionGranted: true };
    }

    setActivePushToken(token);

    const osPlatform = Platform.OS === "ios" ? "ios" : "android";
    for (const tenantId of tenantIds) {
      void registerPushToken(tenantId, {
        token,
        platform: osPlatform,
      });
    }

    return { success: true, token, permissionGranted: true };
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : "Error initializing push notifications";
    return { success: false, error: errorMsg };
  }
}

/**
 * Listen for user tapping a push notification.
 */
export function addNotificationResponseListener(
  callback: (response: {
    notification: {
      request: {
        content: {
          data?: Record<string, unknown>;
        };
      };
    };
  }) => void,
): { remove: () => void } {
  const notif = getNotificationsModule();
  if (!notif) {
    return { remove: () => {} };
  }
  try {
    return notif.addNotificationResponseReceivedListener(callback as never);
  } catch {
    return { remove: () => {} };
  }
}

/**
 * Register push token with the backend notification service.
 */
export async function registerPushToken(
  tenantId: string,
  payload: PushTokenPayload,
): Promise<boolean> {
  try {
    await request(`/api/v1/tenants/${tenantId}/notifications/push-subscription`, {
      method: "POST",
      body: payload,
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Fetch unread notifications count safely for the active business.
 */
export async function fetchUnreadCount(tenantId: string): Promise<number> {
  try {
    const res = await getUnreadNotificationCount(tenantId);
    return res.unread ?? 0;
  } catch {
    return 0;
  }
}

/**
 * Fetch user inbox notifications safely.
 */
export async function fetchInboxNotifications(tenantId: string): Promise<AppNotification[]> {
  try {
    return await getNotifications(tenantId, false);
  } catch {
    return [];
  }
}

/**
 * Mark a notification as read safely.
 */
export async function acknowledgeNotification(tenantId: string, notificationId: string): Promise<boolean> {
  try {
    await markNotificationRead(tenantId, notificationId);
    return true;
  } catch {
    return false;
  }
}

/**
 * Send a test push notification to this device.
 */
export async function sendMobileTestPush(
  tenantId: string,
  variant: "brief" | "detailed" | "multimedia" = "brief",
): Promise<{ success: boolean; message: string }> {
  try {
    const res = await request<{ status: string; delivered_endpoints?: number }>(
      `/api/v1/tenants/${tenantId}/notifications/test-push`,
      {
        method: "POST",
        body: { type: variant },
      },
    );
    return {
      success: true,
      message: `Test push sent (${res.delivered_endpoints ?? 0} endpoint notified)!`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to trigger test push.";
    return { success: false, message };
  }
}
