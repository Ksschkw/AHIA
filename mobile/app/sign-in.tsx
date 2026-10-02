import * as Haptics from "expo-haptics";
import { Link, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Animated, { FadeInDown, FadeInUp } from "react-native-reanimated";

import { AhiaMark } from "@/components/ahia-mark";
import { CredentialField } from "@/components/credential-field";
import { ChevronLeftIcon, LockIcon } from "@/components/icons";
import { ApiError, signIn } from "@/lib/api";

/**
 * Sign In Screen.
 *
 * Polished, high-contrast entry point matching world-class fintech design standards.
 * Built with dynamic keyboard management that keeps all inputs in the top half of the screen,
 * ensuring zero obstruction from mobile soft keyboards.
 */
export default function SignIn() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // Dynamic soft keyboard tracking
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [keyboardHeight, setKeyboardHeight] = useState(0);

  useEffect(() => {
    const showSub = Keyboard.addListener(
      Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow",
      (e) => {
        setKeyboardVisible(true);
        setKeyboardHeight(e.endCoordinates.height);
      },
    );
    const hideSub = Keyboard.addListener(
      Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide",
      () => {
        setKeyboardVisible(false);
        setKeyboardHeight(0);
      },
    );

    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  async function submit() {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setProblem(null);
    setBusy(true);
    try {
      await signIn(identifier.trim(), password);
      router.replace("/home");
    } catch (error) {
      setProblem(
        error instanceof ApiError ? error.message : "We could not reach the shop. Check your connection.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.keyboardContainer}
      keyboardVerticalOffset={Platform.OS === "ios" ? 10 : 0}
    >
      <ScrollView
        contentContainerStyle={[
          styles.scrollContent,
          { paddingBottom: keyboardVisible ? keyboardHeight + 80 : 40 },
        ]}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        automaticallyAdjustKeyboardInsets={true}
        showsVerticalScrollIndicator={false}
      >
        {/* Top Back Navigation */}
        <Animated.View entering={FadeInDown.duration(300)} style={styles.topNav}>
          <Pressable
            style={({ pressed }) => [styles.backBtn, pressed && styles.backBtnPressed]}
            onPress={() => router.back()}
            accessibilityRole="button"
            accessibilityLabel="Go back"
          >
            <ChevronLeftIcon size={18} color="#084a2f" />
            <Text style={styles.backBtnText}>Back</Text>
          </Pressable>
        </Animated.View>

        {/* Header - Collapses gracefully when keyboard is active to keep inputs at top */}
        {!keyboardVisible ? (
          <Animated.View entering={FadeInDown.duration(400).delay(80)} style={styles.header}>
            <View style={styles.markWrap}>
              <AhiaMark />
            </View>
            <Text style={styles.title}>Welcome back</Text>
            <Text style={styles.subtitle}>
              Sign in to manage your stall, price customer lists, and record daily sales.
            </Text>
          </Animated.View>
        ) : (
          <View style={styles.compactHeader}>
            <Text style={styles.compactTitle}>Sign in to AHIA</Text>
          </View>
        )}

        {/* Input Card - Positioned in the upper half of screen */}
        <Animated.View entering={FadeInUp.duration(450).delay(150)} style={styles.card}>
          <CredentialField
            label="Phone number or email"
            value={identifier}
            onChange={setIdentifier}
            placeholder="0803 123 4567 or you@example.com"
            keyboardType="default"
            autoComplete="username"
            textContentType="username"
          />

          <CredentialField
            label="Password"
            value={password}
            onChange={setPassword}
            secret
            autoComplete="current-password"
            textContentType="password"
          />

          {problem ? (
            <View style={styles.problemBox}>
              <Text style={styles.problemText}>{problem}</Text>
            </View>
          ) : null}

          {/* Bubbly Curved Button */}
          <Pressable
            style={({ pressed }) => [
              styles.button,
              (busy || identifier.trim().length < 3 || password.length < 1) && styles.buttonDisabled,
              pressed && styles.buttonPressed,
            ]}
            disabled={busy || identifier.trim().length < 3 || password.length < 1}
            onPress={() => void submit()}
            accessibilityRole="button"
          >
            {busy ? (
              <ActivityIndicator color="#ffffff" size="small" />
            ) : (
              <Text style={styles.buttonText}>Sign in to your stall</Text>
            )}
          </Pressable>
        </Animated.View>

        {/* Footer Navigation */}
        <Animated.View entering={FadeInUp.duration(400).delay(250)} style={styles.footer}>
          <Text style={styles.footerPrompt}>New to AHIA?</Text>
          <Link href="/register" asChild>
            <Pressable accessibilityRole="button" style={styles.link}>
              <Text style={styles.linkText}>Create a new account</Text>
            </Pressable>
          </Link>
        </Animated.View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  keyboardContainer: {
    flex: 1,
    backgroundColor: "#f8f6f0",
  },
  scrollContent: {
    paddingHorizontal: 20,
    paddingTop: Platform.OS === "android" ? 24 : 12,
    justifyContent: "flex-start",
  },
  topNav: {
    marginBottom: 12,
  },
  backBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 999,
    backgroundColor: "rgba(8, 74, 47, 0.08)",
  },
  backBtnPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.98 }],
  },
  backBtnText: {
    fontSize: 13,
    fontWeight: "700",
    color: "#084a2f",
  },
  header: {
    alignItems: "center",
    marginBottom: 20,
    paddingHorizontal: 16,
  },
  compactHeader: {
    alignItems: "center",
    marginBottom: 12,
  },
  compactTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0f172a",
  },
  markWrap: {
    marginBottom: 12,
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 4,
  },
  title: {
    fontSize: 26,
    fontWeight: "800",
    color: "#0f172a",
    letterSpacing: -0.5,
    marginBottom: 6,
    textAlign: "center",
  },
  subtitle: {
    fontSize: 14,
    color: "#64748b",
    textAlign: "center",
    lineHeight: 20,
    maxWidth: 320,
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 24,
    padding: 22,
    gap: 16,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 16,
    elevation: 4,
  },
  problemBox: {
    backgroundColor: "#fef2f2",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#fecaca",
    padding: 12,
  },
  problemText: {
    color: "#b91c1c",
    fontSize: 13,
    fontWeight: "600",
    lineHeight: 18,
  },
  button: {
    backgroundColor: "#084a2f",
    minHeight: 56,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 6,
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.28,
    shadowRadius: 14,
    elevation: 6,
  },
  buttonDisabled: {
    opacity: 0.5,
    shadowOpacity: 0,
    elevation: 0,
  },
  buttonPressed: {
    transform: [{ scale: 0.98 }],
    opacity: 0.9,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginTop: 24,
    paddingVertical: 12,
  },
  footerPrompt: {
    fontSize: 14,
    color: "#64748b",
    fontWeight: "500",
  },
  link: {
    paddingVertical: 4,
    paddingHorizontal: 6,
  },
  linkText: {
    fontSize: 14,
    fontWeight: "700",
    color: "#084a2f",
  },
});
