import { Link, useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { AhiaMark } from "@/components/ahia-mark";
import { CredentialField } from "@/components/credential-field";
import { ChevronLeftIcon } from "@/components/icons";
import { ApiError, signIn } from "@/lib/api";

/**
 * Sign In Screen.
 *
 * Polished, high-contrast entry point matching AHIA web styling.
 * Supports phone number or email identifier with automatic keyboard optimization.
 */
export default function SignIn() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit() {
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
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
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
        <Text style={styles.title}>Welcome back</Text>
        <Text style={styles.subtitle}>
          Sign in to manage your stall, price customer lists, and record daily sales.
        </Text>
      </View>

      <View style={styles.card}>
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

        <Pressable
          style={[styles.button, busy ? styles.buttonBusy : null]}
          disabled={busy || identifier.trim().length < 3 || password.length < 1}
          onPress={() => void submit()}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.buttonText}>Sign in to your stall</Text>
          )}
        </Pressable>
      </View>

      <View style={styles.footer}>
        <Text style={styles.footerPrompt}>New to AHIA?</Text>
        <Link href="/register" asChild>
          <Pressable accessibilityRole="button" style={styles.link}>
            <Text style={styles.linkText}>Create a new account</Text>
          </Pressable>
        </Link>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: {
    padding: 24,
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
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderRadius: 8,
    backgroundColor: "#e8eee2",
  },
  backBtnText: {
    color: "#084a2f",
    fontSize: 14,
    fontWeight: "700",
  },
  header: {
    alignItems: "center",
    marginBottom: 24,
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
    gap: 16,
    borderWidth: 1,
    borderColor: "#e5ded2",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
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
    minHeight: 52,
    borderRadius: 10,
    backgroundColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 6,
  },
  buttonBusy: {
    opacity: 0.7,
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
    marginTop: 24,
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
