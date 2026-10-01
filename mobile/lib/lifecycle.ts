import { useEffect, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

export interface LifecycleCallbacks {
  onResume?: () => void | Promise<void>;
  onPause?: () => void | Promise<void>;
  onStop?: () => void | Promise<void>;
}

/**
 * Mobile application lifecycle hook.
 *
 * Translates React Native / Android AppState transitions into lifecycle callbacks:
 * - onResume: App transitioned to active foreground (e.g., app reopened, resumed from background)
 * - onPause / onStop: App entered background or inactive state
 */
export function useAppLifecycle(callbacks: LifecycleCallbacks): void {
  const appState = useRef<AppStateStatus>(AppState.currentState);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextAppState: AppStateStatus) => {
      const prev = appState.current;

      if (prev.match(/inactive|background/) && nextAppState === "active") {
        // App has come to the foreground (onResume)
        void callbacks.onResume?.();
      } else if (prev === "active" && nextAppState.match(/inactive|background/)) {
        // App has moved to the background (onPause / onStop)
        void callbacks.onPause?.();
        void callbacks.onStop?.();
      }

      appState.current = nextAppState;
    });

    return () => {
      subscription.remove();
    };
  }, [callbacks]);
}
