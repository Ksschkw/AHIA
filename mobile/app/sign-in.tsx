import { Link, useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { CredentialField } from "@/components/credential-field";
import { ApiError, signIn } from "@/lib/api";

/**
 * Signing in.
 *
 * One identifier field rather than separate phone and email boxes, because that is what the API takes and
 * because a trader types whichever he remembers. A trader signs in once and expects never to again: the client
 * refreshes the access token silently on any 401, so nothing here asks for a password twice.
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
      <Text style={styles.title}>Sign in</Text>
      <CredentialField
        label="Phone number or email"
        value={identifier}
        onChange={setIdentifier}
        placeholder="0803 123 4567"
        keyboardType="phone-pad"
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
      {problem ? <Text style={styles.problem}>{problem}</Text> : null}
      <Pressable
        style={[styles.button, busy ? styles.buttonBusy : null]}
        disabled={busy || identifier.trim().length < 3 || password.length < 1}
        onPress={() => void submit()}
        accessibilityRole="button"
      >
        <Text style={styles.buttonText}>{busy ? "Signing in..." : "Sign in"}</Text>
      </Pressable>
      {busy ? <ActivityIndicator color="#0b5d3b" /> : null}
      <Link href="/register" asChild>
        <Pressable accessibilityRole="button" style={styles.link}>
          <Text style={styles.linkText}>No account yet? Create one</Text>
        </Pressable>
      </Link>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 16, backgroundColor: "#f7f3ec", flexGrow: 1, justifyContent: "center" },
  title: { fontSize: 30, fontWeight: "800", color: "#1e1b16", marginBottom: 8 },
  problem: { color: "#a3372b", fontSize: 15, lineHeight: 21 },
  button: {
    minHeight: 54,
    borderRadius: 10,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  buttonBusy: { opacity: 0.6 },
  buttonText: { color: "#ffffff", fontSize: 17, fontWeight: "700" },
  link: { alignItems: "center", paddingVertical: 10 },
  linkText: { color: "#0b5d3b", fontSize: 15, fontWeight: "600" },
});
