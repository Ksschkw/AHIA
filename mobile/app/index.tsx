import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

/**
 * The front door.
 *
 * A trader who has never seen this app does not know what it is, and a screen that opens with two empty boxes
 * asking for a password tells him nothing. This says what the product does, in the order he would say it - the
 * shelf, the list, the waybill - and then offers the two things he can do.
 *
 * It is also where he chooses **Sign in** or **Create an account**, which the first version of this app did not
 * offer at all: it opened straight into a sign-in form, so somebody without an account had nowhere to go.
 */
export default function Welcome() {
  return (
    <View style={styles.page}>
      <View style={styles.head}>
        <Text style={styles.brand}>AHIA</Text>
        <Text style={styles.line}>What is on the shelf, what a list comes to, and what you made on it.</Text>
      </View>

      <View style={styles.points}>
        <Point title="Your shelf" detail="The goods, with their prices, in your hand." />
        <Point title="Their list" detail="Sent from a phone, priced by you, read under your headings." />
        <Point title="The waybill" detail="Who is carrying it, under what number, and what it cost." />
      </View>

      <View style={styles.actions}>
        <Link href="/sign-in" asChild>
          <Pressable style={styles.primary} accessibilityRole="button">
            <Text style={styles.primaryText}>Sign in</Text>
          </Pressable>
        </Link>
        <Link href="/register" asChild>
          <Pressable style={styles.secondary} accessibilityRole="button">
            <Text style={styles.secondaryText}>Create an account</Text>
          </Pressable>
        </Link>
      </View>
    </View>
  );
}

function Point({ title, detail }: { title: string; detail: string }) {
  return (
    <View style={styles.point}>
      <Text style={styles.pointTitle}>{title}</Text>
      <Text style={styles.pointDetail}>{detail}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "space-between", padding: 24, backgroundColor: "#f7f3ec" },
  head: { marginTop: 48, gap: 10 },
  brand: { fontSize: 40, fontWeight: "800", color: "#0b5d3b", letterSpacing: -1 },
  line: { fontSize: 17, color: "#5c5549", lineHeight: 24 },
  points: { gap: 18 },
  point: { gap: 2 },
  pointTitle: { fontSize: 17, fontWeight: "700", color: "#1e1b16" },
  pointDetail: { fontSize: 15, color: "#5c5549", lineHeight: 21 },
  actions: { gap: 10, marginBottom: 12 },
  primary: {
    minHeight: 54,
    borderRadius: 10,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: "#ffffff", fontSize: 17, fontWeight: "700" },
  secondary: {
    minHeight: 54,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryText: { color: "#0b5d3b", fontSize: 17, fontWeight: "700" },
});
