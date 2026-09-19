import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { ApiError, request } from "@/lib/api";
import { forgetSession } from "@/lib/session";

/**
 * What he sees once he is in.
 *
 * For now it is the proof that the session works: the businesses come from an authenticated call carrying the
 * bearer token and nothing else, so if the name appears, the credential that was written to the keychain is
 * being read back and used. The shelf itself is the next piece of work and this screen is where it will live.
 */
export default function Home() {
  const router = useRouter();
  const [businesses, setBusinesses] = useState<{ id: string; name: string }[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setBusinesses(await request<{ id: string; name: string }[]>("/api/v1/tenants"));
      } catch (error) {
        setProblem(error instanceof ApiError ? error.message : "We could not reach the shop.");
      }
    })();
  }, []);

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <Text style={styles.title}>Your businesses</Text>
      {problem ? <Text style={styles.problem}>{problem}</Text> : null}
      {businesses === null && problem === null ? <ActivityIndicator color="#0b5d3b" /> : null}
      {businesses?.length === 0 ? (
        <Text style={styles.hint}>
          No business yet. The next release creates one here, with its name and its money.
        </Text>
      ) : null}
      {businesses?.map((business) => (
        <View key={business.id} style={styles.card}>
          <Text style={styles.cardName}>{business.name}</Text>
          <Text style={styles.cardHint}>The shelf comes next.</Text>
        </View>
      ))}
      <Pressable
        style={styles.signOut}
        accessibilityRole="button"
        onPress={() => {
          void (async () => {
            await forgetSession();
            router.replace("/");
          })();
        }}
      >
        <Text style={styles.signOutText}>Sign out</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 14, backgroundColor: "#f7f3ec", flexGrow: 1 },
  title: { fontSize: 28, fontWeight: "800", color: "#1e1b16", marginBottom: 6 },
  hint: { fontSize: 15, color: "#5c5549", lineHeight: 22 },
  problem: { color: "#a3372b", fontSize: 15 },
  card: {
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 12,
    padding: 16,
    gap: 4,
    backgroundColor: "#ffffff",
  },
  cardName: { fontSize: 18, fontWeight: "700", color: "#1e1b16" },
  cardHint: { fontSize: 14, color: "#5c5549" },
  signOut: { marginTop: 12, alignItems: "center", paddingVertical: 12 },
  signOutText: { color: "#a3372b", fontSize: 15, fontWeight: "600" },
});
