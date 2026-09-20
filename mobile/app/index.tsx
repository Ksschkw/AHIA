import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";

import { AhiaMark } from "@/components/ahia-mark";
import { PressButton } from "@/components/press-button";

/**
 * The front door.
 *
 * A trader who has never seen this app does not know what it is, and two empty boxes asking for a password tell
 * him nothing. This says what the product does in his own words - the shelf, the list, the waybill - and then
 * offers the two things he can do.
 *
 * Everything moves **once, on arrival**, and then stops. A screen that animates forever is a screen that drains
 * a battery and distracts a man with a customer waiting; the only motion left after the entrance is the mark's
 * own slow breathing, which is a brand rather than a spinner.
 */
export default function Welcome() {
  const router = useRouter();

  return (
    <LinearGradient colors={["#f7f3ec", "#efe8db", "#e6ecdf"]} style={styles.page}>
      <View style={styles.head}>
        <AhiaMark />
        <Animated.View entering={FadeInDown.delay(220).duration(520)}>
          <Text style={styles.brand}>AHIA</Text>
        </Animated.View>
        <Animated.View entering={FadeInDown.delay(320).duration(520)}>
          <Text style={styles.line}>
            What is on the shelf, what a list comes to, and what you made on it.
          </Text>
        </Animated.View>
      </View>

      <View style={styles.points}>
        <Point
          delay={460}
          title="Your shelf"
          detail="The goods, with their prices, in your hand."
        />
        <Point
          delay={580}
          title="Their list"
          detail="Sent from a phone, priced by you, read under your headings."
        />
        <Point
          delay={700}
          title="The waybill"
          detail="Who is carrying it, under what number, and what it cost."
        />
      </View>

      <Animated.View entering={FadeInDown.delay(840).duration(520)} style={styles.actions}>
        <PressButton label="Sign in" onPress={() => router.push("/sign-in")} />
        <PressButton
          label="Create an account"
          tone="outline"
          onPress={() => router.push("/register")}
        />
      </Animated.View>
    </LinearGradient>
  );
}

/**
 * One promise, arriving a beat after the one above it.
 *
 * The stagger is not decoration: three lines that appear together are read as a block, and three that arrive in
 * sequence are read one at a time, which is how somebody actually reads a screen they have never seen.
 */
function Point({ title, detail, delay }: { title: string; detail: string; delay: number }) {
  return (
    <Animated.View entering={FadeInDown.delay(delay).duration(480)} style={styles.point}>
      <View style={styles.dot} />
      <View style={styles.pointBody}>
        <Text style={styles.pointTitle}>{title}</Text>
        <Text style={styles.pointDetail}>{detail}</Text>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "space-between", paddingHorizontal: 24, paddingTop: 56, paddingBottom: 32 },
  head: { alignItems: "center", gap: 14 },
  brand: { fontSize: 42, fontWeight: "800", color: "#0b5d3b", letterSpacing: -1, textAlign: "center" },
  line: {
    fontSize: 17,
    color: "#5c5549",
    lineHeight: 25,
    textAlign: "center",
    maxWidth: 320,
  },
  points: { gap: 20 },
  point: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#0b5d3b", marginTop: 7 },
  pointBody: { flex: 1, gap: 3 },
  pointTitle: { fontSize: 17, fontWeight: "700", color: "#1e1b16" },
  pointDetail: { fontSize: 15, color: "#5c5549", lineHeight: 21 },
  actions: { gap: 12 },
});
