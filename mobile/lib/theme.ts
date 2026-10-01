import * as SecureStore from "expo-secure-store";

export type ThemeMode = "light" | "dark";

export interface ThemePalette {
  mode: ThemeMode;
  bg: string;
  card: string;
  cardHover: string;
  border: string;
  borderLight: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  accent: string;
  accentLight: string;
  accentText: string;
  inputBg: string;
  inputBorder: string;
  badgeBg: string;
  danger: string;
  dangerBg: string;
  warning: string;
  warningBg: string;
  navBg: string;
  navBorder: string;
  modalBackdrop: string;
}

export const lightTheme: ThemePalette = {
  mode: "light",
  bg: "#fbf7f0",
  card: "#ffffff",
  cardHover: "#f8fafc",
  border: "#e2e8f0",
  borderLight: "#f1f5f9",
  text: "#0f172a",
  textSecondary: "#475569",
  textMuted: "#64748b",
  accent: "#084a2f",
  accentLight: "#e6f4ea",
  accentText: "#084a2f",
  inputBg: "#ffffff",
  inputBorder: "#cbd5e1",
  badgeBg: "#f1f5f9",
  danger: "#dc2626",
  dangerBg: "#fee2e2",
  warning: "#d97706",
  warningBg: "#fef3c7",
  navBg: "#ffffff",
  navBorder: "#e2e8f0",
  modalBackdrop: "rgba(0, 0, 0, 0.65)",
};

export const darkTheme: ThemePalette = {
  mode: "dark",
  bg: "#0d1117",
  card: "#161b22",
  cardHover: "#21262d",
  border: "#30363d",
  borderLight: "#21262d",
  text: "#f0f6fc",
  textSecondary: "#8b949e",
  textMuted: "#6e7681",
  accent: "#238636",
  accentLight: "#122b1d",
  accentText: "#4ade80",
  inputBg: "#0d1117",
  inputBorder: "#30363d",
  badgeBg: "#21262d",
  danger: "#ef4444",
  dangerBg: "#450a0a",
  warning: "#f59e0b",
  warningBg: "#451a03",
  navBg: "#161b22",
  navBorder: "#30363d",
  modalBackdrop: "rgba(0, 0, 0, 0.75)",
};

const THEME_KEY = "ahia.mobile_theme";

export async function getSavedThemeMode(): Promise<ThemeMode> {
  try {
    const saved = await SecureStore.getItemAsync(THEME_KEY);
    if (saved === "dark") return "dark";
    return "light";
  } catch {
    return "light";
  }
}

export async function saveThemeMode(mode: ThemeMode): Promise<void> {
  try {
    await SecureStore.setItemAsync(THEME_KEY, mode);
  } catch {
    // Non-fatal
  }
}

export function getTheme(mode: ThemeMode): ThemePalette {
  return mode === "dark" ? darkTheme : lightTheme;
}
