import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  acceptInvitation,
  currentUser,
  listMyInvitations,
  type AcceptedInvitation,
  type PendingInvitation,
} from "@/lib/api";

export default function Join() {
  const router = useRouter();
  const params = useLocalSearchParams<{ token?: string }>();
  const initialToken = typeof params.token === "string" ? params.token : "";

  const [token, setToken] = useState(initialToken);
  const [pendingInvitations, setPendingInvitations] = useState<PendingInvitation[]>([]);
  const [accepted, setAccepted] = useState<AcceptedInvitation | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        await currentUser();
        const pending = await listMyInvitations().catch(() => []);
        setPendingInvitations(pending);
      } catch {
        // Not signed in
        router.replace("/sign-in");
        return;
      } finally {
        setCheckingAuth(false);
      }

      if (initialToken.trim()) {
        await handleAccept(initialToken.trim());
      }
    })();
  }, [initialToken]);

  async function handleAccept(tokenToAccept: string) {
    if (!tokenToAccept.trim()) return;
    setProblem(null);
    setBusy(true);
    try {
      const result = await acceptInvitation(tokenToAccept.trim());
      setAccepted(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not accept invitation. Please check the code.";
      setProblem(msg);
    } finally {
      setBusy(false);
    }
  }

  if (checkingAuth) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#084a2f" />
        <Text style={styles.loadingText}>Checking invitation...</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <View style={styles.header}>
        <Text style={styles.title}>Join a Business</Text>
        <Text style={styles.subtitle}>
          Accept an invite or enter an invitation token from your shop owner.
        </Text>
      </View>

      {accepted ? (
        <View style={styles.successCard}>
          <Text style={styles.successTitle}>You are in!</Text>
          <Text style={styles.successBody}>
            You have successfully joined {accepted.tenant_name} as {accepted.role_name}.
          </Text>
          <Pressable
            style={styles.primaryBtn}
            onPress={() => router.replace("/home")}
          >
            <Text style={styles.primaryBtnText}>Open Shop</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card}>
          {problem ? <Text style={styles.problemText}>{problem}</Text> : null}

          {pendingInvitations.length > 0 ? (
            <View style={styles.pendingSection}>
              <Text style={styles.sectionHeading}>Pending Invitations for You</Text>
              {pendingInvitations.map((inv) => (
                <View key={inv.id} style={styles.invitationRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.invTenantName}>{inv.tenant_name}</Text>
                    <Text style={styles.invRole}>Role: {inv.role_name}</Text>
                  </View>
                  <Pressable
                    style={styles.acceptBtn}
                    onPress={() => handleAccept(inv.id)}
                    disabled={busy}
                  >
                    <Text style={styles.acceptBtnText}>Accept</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          ) : null}

          <View style={styles.inputSection}>
            <Text style={styles.inputLabel}>Invitation Token / Code</Text>
            <TextInput
              style={styles.input}
              placeholder="Paste invitation token here"
              placeholderTextColor="#8a928e"
              value={token}
              onChangeText={setToken}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <Pressable
              style={[styles.primaryBtn, (!token.trim() || busy) ? styles.btnDisabled : null]}
              disabled={!token.trim() || busy}
              onPress={() => handleAccept(token)}
            >
              {busy ? (
                <ActivityIndicator color="#ffffff" size="small" />
              ) : (
                <Text style={styles.primaryBtnText}>Join Business</Text>
              )}
            </Pressable>
          </View>

          <Pressable style={styles.backBtn} onPress={() => router.replace("/home")}>
            <Text style={styles.backBtnText}>Back to Home</Text>
          </Pressable>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: "#0d1117",
    padding: 20,
    justifyContent: "center",
  },
  center: {
    flex: 1,
    backgroundColor: "#0d1117",
    alignItems: "center",
    justifyContent: "center",
  },
  loadingText: {
    color: "#8b949e",
    marginTop: 12,
    fontSize: 14,
  },
  header: {
    marginBottom: 24,
    alignItems: "center",
  },
  title: {
    color: "#f0f6fc",
    fontSize: 24,
    fontWeight: "800",
    marginBottom: 8,
  },
  subtitle: {
    color: "#8b949e",
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  card: {
    backgroundColor: "#161b22",
    borderRadius: 14,
    padding: 20,
    borderWidth: 1,
    borderColor: "#30363d",
  },
  pendingSection: {
    marginBottom: 20,
    borderBottomWidth: 1,
    borderBottomColor: "#21262d",
    paddingBottom: 16,
  },
  sectionHeading: {
    color: "#4ade80",
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 12,
  },
  invitationRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: "#0d1117",
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
  },
  invTenantName: {
    color: "#f0f6fc",
    fontSize: 15,
    fontWeight: "700",
  },
  invRole: {
    color: "#8b949e",
    fontSize: 12,
    marginTop: 2,
  },
  acceptBtn: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 6,
  },
  acceptBtnText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  inputSection: {
    marginTop: 8,
  },
  inputLabel: {
    color: "#8b949e",
    fontSize: 13,
    marginBottom: 8,
    fontWeight: "600",
  },
  input: {
    backgroundColor: "#0d1117",
    color: "#f0f6fc",
    borderRadius: 8,
    padding: 12,
    fontSize: 14,
    borderWidth: 1,
    borderColor: "#30363d",
    marginBottom: 14,
  },
  primaryBtn: {
    backgroundColor: "#084a2f",
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: "center",
  },
  btnDisabled: {
    opacity: 0.5,
  },
  primaryBtnText: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "700",
  },
  problemText: {
    color: "#f87171",
    fontSize: 13,
    marginBottom: 14,
    lineHeight: 18,
  },
  backBtn: {
    marginTop: 16,
    alignItems: "center",
    paddingVertical: 8,
  },
  backBtnText: {
    color: "#8b949e",
    fontSize: 14,
  },
  successCard: {
    backgroundColor: "#161b22",
    borderRadius: 14,
    padding: 24,
    borderWidth: 1,
    borderColor: "#084a2f",
    alignItems: "center",
  },
  successTitle: {
    color: "#4ade80",
    fontSize: 22,
    fontWeight: "800",
    marginBottom: 10,
  },
  successBody: {
    color: "#f0f6fc",
    fontSize: 15,
    textAlign: "center",
    lineHeight: 22,
    marginBottom: 20,
  },
});
