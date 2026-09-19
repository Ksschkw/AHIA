import { useRouter } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { CredentialField } from "@/components/credential-field";
import { ApiError, registerAccount } from "@/lib/api";

/**
 * Creating an account.
 *
 * The same fields the API asks for and no more, with one addition: **the password is typed twice**. The API
 * does not require it - it takes one password - but a person typing a password they cannot see, once, on a
 * phone, will eventually lock themselves out of an account they just made.
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
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>Create your account</Text>
      <Text style={styles.hint}>
        One account, however many businesses you run. You will give each business its own name next.
      </Text>
      <CredentialField label="First name" value={firstName} onChange={setFirstName} placeholder="Ada" />
      <CredentialField
        label="Last name (optional)"
        value={lastName}
        onChange={setLastName}
        placeholder="Obi"
      />
      <CredentialField
        label="Phone number"
        value={phone}
        onChange={setPhone}
        placeholder="0803 123 4567"
        keyboardType="phone-pad"
      />
      <CredentialField label="Password" value={password} onChange={setPassword} secret />
      <CredentialField label="Password again" value={again} onChange={setAgain} secret />
      {mismatch ? <Text style={styles.problem}>The two passwords do not match.</Text> : null}
      {problem ? <Text style={styles.problem}>{problem}</Text> : null}
      <Pressable
        style={[styles.button, busy || !ready ? styles.buttonBusy : null]}
        disabled={busy || !ready}
        onPress={() => void submit()}
        accessibilityRole="button"
      >
        <Text style={styles.buttonText}>{busy ? "Creating..." : "Create my account"}</Text>
      </Pressable>
      {busy ? <ActivityIndicator color="#0b5d3b" /> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 14, backgroundColor: "#f7f3ec", flexGrow: 1, justifyContent: "center" },
  title: { fontSize: 30, fontWeight: "800", color: "#1e1b16" },
  hint: { fontSize: 15, color: "#5c5549", lineHeight: 21, marginBottom: 4 },
  problem: { color: "#a3372b", fontSize: 15 },
  button: {
    minHeight: 54,
    borderRadius: 10,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
  },
  buttonBusy: { opacity: 0.6 },
  buttonText: { color: "#ffffff", fontSize: 17, fontWeight: "700" },
});
