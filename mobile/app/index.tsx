import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError, request, signIn } from "@/lib/api";

/**
 * Signing in, on a phone.
 *
 * The same account, the same password and the same endpoint as the web app. What differs is what happens after
 * the tokens arrive: the refresh token goes to the keychain rather than a cookie jar, which is `lib/session.ts`'s
 * job and the reason this file does not mention storage at all.
 *
 * A trader signs in once and expects never to do it again - the access token is refreshed silently by the client
 * on any 401, so nothing here asks him for a password twice.
 */
export default function SignIn() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [business, setBusiness] = useState<string | null>(null);

  async function submit() {
    setProblem(null);
    setBusy(true);
    try {
      await signIn(phone.trim(), password);
      // Asking for the businesses is the proof that the token works: it is an authenticated call, and it is
      // made with the header alone.
      const tenants = await request<{ name: string }[]>("/api/v1/tenants");
      setBusiness(tenants[0]?.name ?? "no business yet");
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "We could not reach the shop.");
    } finally {
      setBusy(false);
    }
  }

  if (business !== null) {
    return (
      <View style={styles.page}>
        <Text style={styles.title}>{business}</Text>
        <Text style={styles.hint}>
          Signed in. The shelf comes next, and it will work with no signal.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.page}>
      <Text style={styles.title}>AHIA</Text>
      <Text style={styles.hint}>Your shop, your list, your waybill.</Text>
      <TextInput
        style={styles.field}
        value={phone}
        onChangeText={setPhone}
        placeholder="Phone number"
        keyboardType="phone-pad"
        autoCapitalize="none"
        accessibilityLabel="Phone number"
      />
      <TextInput
        style={styles.field}
        value={password}
        onChangeText={setPassword}
        placeholder="Password"
        secureTextEntry
        accessibilityLabel="Password"
      />
      {problem ? <Text style={styles.problem}>{problem}</Text> : null}
      <Pressable
        style={[styles.button, busy ? styles.buttonBusy : null]}
        disabled={busy || phone.trim().length < 7 || password.length < 8}
        onPress={() => void submit()}
      >
        <Text style={styles.buttonText}>{busy ? "Signing in..." : "Sign in"}</Text>
      </Pressable>
      {busy ? <ActivityIndicator color="#0b5d3b" /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "center", padding: 24, gap: 12, backgroundColor: "#f7f3ec" },
  title: { fontSize: 34, fontWeight: "800", color: "#1e1b16", letterSpacing: -0.5 },
  hint: { fontSize: 15, color: "#5c5549", marginBottom: 8 },
  field: {
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 10,
    paddingHorizontal: 14,
    minHeight: 52,
    fontSize: 16,
    backgroundColor: "#ffffff",
  },
  problem: { color: "#a3372b", fontSize: 14 },
  button: {
    minHeight: 52,
    borderRadius: 10,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  buttonBusy: { opacity: 0.6 },
  buttonText: { color: "#ffffff", fontSize: 16, fontWeight: "700" },
});
