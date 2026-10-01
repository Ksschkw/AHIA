/**
 * Push notification & In-app notification infrastructure for AHIA Mobile.
 *
 * Provides safe device token registration and unread notification state management.
 */

import { getUnreadNotificationCount, getNotifications, markNotificationRead, type AppNotification } from "./api";

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
