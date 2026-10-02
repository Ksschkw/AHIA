import * as Haptics from "expo-haptics";
import { Link, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { AhiaMark } from "@/components/ahia-mark";
import { CredentialField } from "@/components/credential-field";
import { ChevronLeftIcon } from "@/components/icons";
import { ApiError, registerAccount } from "@/lib/api";

/**
 * Register Account Screen.
 *
 * Professional onboarding flow with automatic keyboard avoidance and bubbly tactile buttons.
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
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      style={{ flex: 1, backgroundColor: "#fbf7f0" }}
      keyboardVerticalOffset={Platform.OS === "ios" ? 0 : 25}
    >
      <ScrollView
        contentContainerStyle={styles.page}
        keyboardShouldPersistTaps="handled"
        automaticallyAdjustKeyboardInsets={true}
      >
      <View style={styles.topNav}>
        <Pressable
          style={styles.backBtn}
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel="Go back"
        >
          <ChevronLeftIcon size={20} color="#084a2f" />
          <Text style={styles.backBtnText}>Back</Text>
        </Pressable>
      </View>

      <View style={styles.header}>
        <View style={styles.markWrap}>
          <AhiaMark />
        </View>
        <Text style={styles.title}>Create your account</Text>
        <Text style={styles.subtitle}>
          One account to run all your businesses. You can name your stall right after signing up.
        </Text>
      </View>

      <View style={styles.card}>
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

        <Pressable
          style={[styles.button, busy || !ready ? styles.buttonBusy : null]}
          disabled={busy || !ready}
          onPress={() => void submit()}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.buttonText}>Create account and open stall</Text>
          )}
        </Pressable>
      </View>

      <View style={styles.footer}>
        <Text style={styles.footerPrompt}>Already have an account?</Text>
        <Link href="/sign-in" asChild>
          <Pressable accessibilityRole="button" style={styles.link}>
            <Text style={styles.linkText}>Sign in</Text>
          </Pressable>
        </Link>
      </View>
    </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  page: {
    padding: 24,
    paddingBottom: 56,
    backgroundColor: "#fbf7f0",
    flexGrow: 1,
    justifyContent: "center",
  },
  topNav: {
    marginBottom: 16,
  },
  backBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 20,
    backgroundColor: "#e8eee2",
  },
  backBtnText: {
    color: "#084a2f",
    fontSize: 14,
    fontWeight: "700",
  },
  header: {
    alignItems: "center",
    marginBottom: 20,
  },
  markWrap: {
    marginBottom: 12,
  },
  title: {
    fontSize: 28,
    fontWeight: "800",
    color: "#1e1b16",
    marginBottom: 8,
    textAlign: "center",
  },
  subtitle: {
    fontSize: 15,
    color: "#5c5549",
    textAlign: "center",
    lineHeight: 22,
    maxWidth: 320,
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 16,
    padding: 20,
    gap: 14,
    borderWidth: 1,
    borderColor: "#e5ded2",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  nameRow: {
    flexDirection: "row",
    gap: 12,
  },
  problemBox: {
    backgroundColor: "#fee2e2",
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#fca5a5",
  },
  problemText: {
    color: "#991b1b",
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "500",
  },
  button: {
    minHeight: 56,
    borderRadius: 28,
    backgroundColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 8,
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.28,
    shadowRadius: 8,
    elevation: 4,
  },
  buttonPressed: {
    transform: [{ scale: 0.98 }],
    opacity: 0.92,
  },
  buttonBusy: {
    opacity: 0.6,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: 20,
  },
  footerPrompt: {
    color: "#5c5549",
    fontSize: 15,
  },
  link: {
    paddingVertical: 4,
  },
  linkText: {
    color: "#084a2f",
    fontSize: 15,
    fontWeight: "700",
    textDecorationLine: "underline",
  },
});
