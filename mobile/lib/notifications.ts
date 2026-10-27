/**
 * Push notification & In-app notification infrastructure for AHIA Mobile.
 *
 * Provides safe device token registration and unread notification state management.
 */

import {
  getUnreadNotificationCount,
  getNotifications,
  markNotificationRead,
  request,
  type AppNotification,
} from "./api";

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
