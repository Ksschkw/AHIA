import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";

import { AhiaMark } from "@/components/ahia-mark";
import { PressButton } from "@/components/press-button";
import { restoreSession } from "@/lib/api";

/**
 * The front door of AHIA Mobile.
 *
 * Automatically restores active sessions from SecureStore without requiring the
 * trader to log in again on app reopen. If no session exists, displays an elegant,
 * professional introduction to the market operating system.
 */
export default function Welcome() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function checkExistingAuth() {
      try {
        const hasSession = await restoreSession();
        if (mounted && hasSession) {
          router.replace("/home");
          return;
        }
      } catch {
        // Fallback to welcome screen on network or keychain issue
      } finally {
        if (mounted) {
          setCheckingAuth(false);
        }
      }
    }
    void checkExistingAuth();
    return () => {
      mounted = false;
    };
  }, [router]);

  if (checkingAuth) {
    return (
      <View style={styles.splashPage}>
        <AhiaMark />
        <Text style={styles.splashBrand}>AHIA</Text>
        <ActivityIndicator color="#084a2f" style={{ marginTop: 24 }} />
      </View>
    );
  }

  return (
    <LinearGradient colors={["#fbf7f0", "#f4ede0", "#e8eee2"]} style={styles.page}>
      <View style={styles.head}>
        <AhiaMark />
        <Animated.View entering={FadeInDown.delay(100).duration(450)}>
          <View style={styles.badgePill}>
            <Text style={styles.badgePillText}>Nigeria Market Operating System</Text>
          </View>
        </Animated.View>
        <Animated.View entering={FadeInDown.delay(200).duration(500)}>
          <Text style={styles.brand}>AHIA</Text>
        </Animated.View>
        <Animated.View entering={FadeInDown.delay(300).duration(500)}>
          <Text style={styles.line}>
            What is on the shelf, what a list comes to, and what you made on it today.
          </Text>
        </Animated.View>
      </View>

      <View style={styles.points}>
        <Point
          delay={400}
          title="Digital Shelf & Sync"
          detail="All your goods and multi-tier prices cached offline in your hand."
        />
        <Point
          delay={500}
          title="Fast WhatsApp Lists"
          detail="Customer requests priced in seconds under organized market headings."
        />
        <Point
          delay={600}
          title="Dispatch & Waybills"
          detail="Who is carrying your goods, destination park, and parcel tracking numbers."
        />
      </View>

      <Animated.View entering={FadeInDown.delay(700).duration(500)} style={styles.actions}>
        <PressButton label="Sign in" onPress={() => router.push("/sign-in")} />
        <PressButton
          label="Create an account"
          tone="outline"
          onPress={() => router.push("/register")}
        />
        <Text style={styles.footerVersion}>AHIA v0.4.0 - Built for the Trader</Text>
      </Animated.View>
    </LinearGradient>
  );
}

function Point({ title, detail, delay }: { title: string; detail: string; delay: number }) {
  return (
    <Animated.View entering={FadeInDown.delay(delay).duration(450)} style={styles.point}>
      <View style={styles.dot} />
      <View style={styles.pointBody}>
        <Text style={styles.pointTitle}>{title}</Text>
        <Text style={styles.pointDetail}>{detail}</Text>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  splashPage: {
    flex: 1,
    backgroundColor: "#fbf7f0",
    justifyContent: "center",
    alignItems: "center",
  },
  splashBrand: {
    fontSize: 36,
    fontWeight: "900",
    color: "#084a2f",
    letterSpacing: -1,
    marginTop: 16,
  },
  page: {
    flex: 1,
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 56,
    paddingBottom: 32,
  },
  head: {
    alignItems: "center",
    gap: 12,
  },
  badgePill: {
    backgroundColor: "#e3efe7",
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#c1e1cc",
  },
  badgePillText: {
    color: "#084a2f",
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  brand: {
    fontSize: 44,
    fontWeight: "900",
    color: "#084a2f",
    letterSpacing: -1.5,
    textAlign: "center",
  },
  line: {
    fontSize: 16,
    color: "#5c5549",
    lineHeight: 24,
    textAlign: "center",
    maxWidth: 320,
  },
  points: {
    gap: 18,
    marginVertical: 12,
  },
  point: {
    flexDirection: "row",
    gap: 14,
    alignItems: "flex-start",
    backgroundColor: "rgba(255, 255, 255, 0.65)",
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#e5ded2",
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#084a2f",
    marginTop: 6,
  },
  pointBody: {
    flex: 1,
    gap: 3,
  },
  pointTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#1e1b16",
  },
  pointDetail: {
    fontSize: 14,
    color: "#5c5549",
    lineHeight: 20,
  },
  actions: {
    gap: 12,
  },
  footerVersion: {
    textAlign: "center",
    color: "#8c8273",
    fontSize: 12,
    marginTop: 6,
  },
});
