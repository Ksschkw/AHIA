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
import { ChevronLeftIcon } from "@/components/icons";
import { ApiError, registerAccount } from "@/lib/api";

/**
 * Register Account Screen.
 *
 * Professional onboarding flow with industry-standard design.
 * Built with dynamic keyboard management that keeps input fields in the top half of the screen,
 * ensuring zero obstruction from mobile soft keyboards.
 */
export default function Register() {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
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

  const mismatch = again.length > 0 && again !== password;
  const ready =
    firstName.trim().length >= 1 && phone.trim().length >= 7 && password.length >= 8 && !mismatch;

  async function submit() {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setProblem(null);
    setBusy(true);
    try {
      await registerAccount({ firstName: firstName.trim(), lastName, phone: phone.trim(), password });
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

        {/* Header - Collapses when keyboard is active to keep fields high up */}
        {!keyboardVisible ? (
          <Animated.View entering={FadeInDown.duration(400).delay(80)} style={styles.header}>
            <View style={styles.markWrap}>
              <AhiaMark />
            </View>
            <Text style={styles.title}>Create your account</Text>
            <Text style={styles.subtitle}>
              One account to run all your businesses. You can name your stall right after signing up.
            </Text>
          </Animated.View>
        ) : (
          <View style={styles.compactHeader}>
            <Text style={styles.compactTitle}>Create AHIA Account</Text>
          </View>
        )}

        {/* Input Card - Positioned in the upper half of screen */}
        <Animated.View entering={FadeInUp.duration(450).delay(150)} style={styles.card}>
          <View style={styles.nameRow}>
            <View style={{ flex: 1 }}>
              <CredentialField
                label="First name"
                value={firstName}
                onChange={setFirstName}
                placeholder="Ada"
                autoComplete="name-given"
                textContentType="givenName"
              />
            </View>
            <View style={{ flex: 1 }}>
              <CredentialField
                label="Last name"
                value={lastName}
                onChange={setLastName}
                placeholder="Obi"
                autoComplete="name-family"
                textContentType="familyName"
              />
            </View>
          </View>

          <CredentialField
            label="Phone number (WhatsApp)"
            value={phone}
            onChange={setPhone}
            placeholder="0803 123 4567"
            keyboardType="phone-pad"
            autoComplete="tel"
            textContentType="telephoneNumber"
          />

          <CredentialField
            label="Password (min 8 chars)"
            value={password}
            onChange={setPassword}
            secret
            autoComplete="new-password"
            textContentType="newPassword"
          />

          <CredentialField
            label="Confirm password"
            value={again}
            onChange={setAgain}
            secret
            autoComplete="new-password"
            textContentType="newPassword"
          />

          {mismatch ? (
            <View style={styles.problemBox}>
              <Text style={styles.problemText}>The two passwords do not match.</Text>
            </View>
          ) : null}

          {problem ? (
            <View style={styles.problemBox}>
              <Text style={styles.problemText}>{problem}</Text>
            </View>
          ) : null}

          {/* Bubbly Curved Button */}
          <Pressable
            style={({ pressed }) => [
              styles.button,
              (busy || !ready) && styles.buttonDisabled,
              pressed && styles.buttonPressed,
            ]}
            disabled={busy || !ready}
            onPress={() => void submit()}
            accessibilityRole="button"
          >
            {busy ? (
              <ActivityIndicator color="#ffffff" size="small" />
            ) : (
              <Text style={styles.buttonText}>Create account</Text>
            )}
          </Pressable>
        </Animated.View>

        {/* Footer Navigation */}
        <Animated.View entering={FadeInUp.duration(400).delay(250)} style={styles.footer}>
          <Text style={styles.footerPrompt}>Already have an account?</Text>
          <Link href="/sign-in" asChild>
            <Pressable accessibilityRole="button" style={styles.link}>
              <Text style={styles.linkText}>Sign in</Text>
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
    marginBottom: 16,
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
    marginBottom: 10,
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 4,
  },
  title: {
    fontSize: 24,
    fontWeight: "800",
    color: "#0f172a",
    letterSpacing: -0.5,
    marginBottom: 4,
    textAlign: "center",
  },
  subtitle: {
    fontSize: 13,
    color: "#64748b",
    textAlign: "center",
    lineHeight: 18,
    maxWidth: 320,
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 24,
    padding: 20,
    gap: 14,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 16,
    elevation: 4,
  },
  nameRow: {
    flexDirection: "row",
    gap: 10,
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
    marginTop: 20,
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
