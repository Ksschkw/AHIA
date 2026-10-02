import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import Animated, { FadeIn, FadeInDown, FadeOut } from "react-native-reanimated";

import { AhiaMark } from "@/components/ahia-mark";
import {
  BoxIcon,
  LockIcon,
  ReceiptIcon,
  ShopIcon,
  SyncIcon,
} from "@/components/icons";
import { restoreSession } from "@/lib/api";

interface SlideItem {
  id: string;
  badge: string;
  title: string;
  subtitle: string;
  icon: (color: string) => React.ReactNode;
}

const SLIDES: SlideItem[] = [
  {
    id: "stall",
    badge: "BUILT FOR NIGERIAN MARKETS",
    title: "Your Entire Stall in Your Pocket",
    subtitle:
      "Manage shelf items, multi-tier normal & wholesale prices, and lightning fast customer tabs from anywhere.",
    icon: (color) => <ShopIcon size={34} color={color} />,
  },
  {
    id: "offline",
    badge: "100% OFFLINE RESILIENT",
    title: "Zero Network? Never Lose a Sale",
    subtitle:
      "Record counter sales, add goods, create categories completely offline. Everything syncs quietly when connectivity returns.",
    icon: (color) => <SyncIcon size={34} color={color} />,
  },
  {
    id: "lists",
    badge: "INSTANT TRADE QUOTES",
    title: "Turn WhatsApp Chats into Priced Lists",
    subtitle:
      "Paste customer messages, price lines with one tap, calculate margins, and send waybill receipts straight to WhatsApp.",
    icon: (color) => <ReceiptIcon size={34} color={color} />,
  },
  {
    id: "security",
    badge: "ROLE CONTROLS & OWNER PIN",
    title: "Total Protection for Your Business",
    subtitle:
      "Separate sales apprentices from sensitive financial numbers. Lock profit margins and store settings behind your 4-digit Owner PIN.",
    icon: (color) => <LockIcon size={34} color={color} />,
  },
];

/**
 * The front door of AHIA Mobile.
 *
 * Automatically restores active sessions from SecureStore without requiring the
 * trader to log in again on app reopen. If no session exists, displays an interactive
 * animated feature film slideshow and tactile bubbly curved buttons.
 */
export default function Welcome() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [activeSlide, setActiveSlide] = useState(0);

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

  // Slideshow auto-advance every 4.8 seconds
  useEffect(() => {
    if (checkingAuth) return;
    const timer = setInterval(() => {
      setActiveSlide((prev) => (prev + 1) % SLIDES.length);
    }, 4800);
    return () => clearInterval(timer);
  }, [checkingAuth]);

  if (checkingAuth) {
    return (
      <View style={styles.splashPage}>
        <AhiaMark />
        <Text style={styles.splashBrand}>AHIA</Text>
        <ActivityIndicator color="#084a2f" style={{ marginTop: 24 }} />
      </View>
    );
  }

  const current = SLIDES[activeSlide];

  return (
    <LinearGradient colors={["#fbf7f0", "#f4ede0", "#e8eee2"]} style={styles.page}>
      {/* Brand Header */}
      <View style={styles.head}>
        <AhiaMark />
        <Animated.View entering={FadeInDown.delay(100).duration(450)}>
          <View style={styles.badgePill}>
            <Text style={styles.badgePillText}>{current.badge}</Text>
          </View>
        </Animated.View>
        <Animated.View entering={FadeInDown.delay(200).duration(450)}>
          <Text style={styles.brand}>AHIA</Text>
        </Animated.View>
      </View>

      {/* Feature Film Slideshow Card */}
      <View style={styles.slideshowContainer}>
        <Pressable
          style={styles.slideCard}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            setActiveSlide((prev) => (prev + 1) % SLIDES.length);
          }}
          accessibilityRole="button"
          accessibilityLabel="Next feature slide"
        >
          <View style={styles.iconCircleWrap}>
            {current.icon("#084a2f")}
          </View>

          <Text style={styles.slideTitle}>{current.title}</Text>
          <Text style={styles.slideSubtitle}>{current.subtitle}</Text>

          {/* Slide Indicator Pills */}
          <View style={styles.indicatorRow}>
            {SLIDES.map((s, idx) => (
              <Pressable
                key={s.id}
                onPress={() => {
                  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                  setActiveSlide(idx);
                }}
                style={[
                  styles.indicatorPill,
                  activeSlide === idx && styles.indicatorPillActive,
                ]}
              />
            ))}
          </View>
        </Pressable>
      </View>

      {/* Tactile Bubbly Curved Action Buttons */}
      <View style={styles.actions}>
        <Pressable
          style={({ pressed }) => [
            styles.bubblyButtonPrimary,
            pressed ? styles.bubblyButtonPressed : null,
          ]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            router.push("/sign-in");
          }}
          accessibilityRole="button"
        >
          <Text style={styles.bubblyButtonTextPrimary}>Sign in to your stall</Text>
        </Pressable>

        <Pressable
          style={({ pressed }) => [
            styles.bubblyButtonSecondary,
            pressed ? styles.bubblyButtonPressed : null,
          ]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            router.push("/register");
          }}
          accessibilityRole="button"
        >
          <Text style={styles.bubblyButtonTextSecondary}>Create a new account</Text>
        </Pressable>

        <Pressable
          style={styles.joinLink}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            router.push("/join" as any);
          }}
        >
          <Text style={styles.joinLinkText}>Invited by stall owner? Join with code</Text>
        </Pressable>

        <Text style={styles.footerVersion}>AHIA v0.4.2 - Market Operating System</Text>
      </View>
    </LinearGradient>
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
    paddingHorizontal: 22,
    paddingTop: 52,
    paddingBottom: 28,
  },
  head: {
    alignItems: "center",
    gap: 10,
  },
  badgePill: {
    backgroundColor: "#e3efe7",
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#c1e1cc",
  },
  badgePillText: {
    color: "#084a2f",
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
  brand: {
    fontSize: 44,
    fontWeight: "900",
    color: "#084a2f",
    letterSpacing: -1.5,
    textAlign: "center",
  },
  slideshowContainer: {
    marginVertical: 12,
  },
  slideCard: {
    backgroundColor: "rgba(255, 255, 255, 0.85)",
    borderRadius: 24,
    padding: 24,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#e5ded2",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 3,
  },
  iconCircleWrap: {
    width: 68,
    height: 68,
    borderRadius: 34,
    backgroundColor: "#e6f4ea",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
    borderWidth: 2,
    borderColor: "#c1e1cc",
  },
  slideTitle: {
    fontSize: 20,
    fontWeight: "800",
    color: "#1e1b16",
    textAlign: "center",
    marginBottom: 8,
  },
  slideSubtitle: {
    fontSize: 14,
    color: "#5c5549",
    textAlign: "center",
    lineHeight: 20,
    paddingHorizontal: 6,
    marginBottom: 18,
  },
  indicatorRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  indicatorPill: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#cbd5e1",
  },
  indicatorPillActive: {
    width: 26,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#084a2f",
  },
  actions: {
    gap: 12,
  },
  bubblyButtonPrimary: {
    minHeight: 56,
    borderRadius: 28,
    backgroundColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 5,
  },
  bubblyButtonSecondary: {
    minHeight: 56,
    borderRadius: 28,
    backgroundColor: "#ffffff",
    borderWidth: 2,
    borderColor: "#084a2f",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 6,
    elevation: 2,
  },
  bubblyButtonPressed: {
    transform: [{ scale: 0.98 }],
    opacity: 0.92,
  },
  bubblyButtonTextPrimary: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  bubblyButtonTextSecondary: {
    color: "#084a2f",
    fontSize: 16,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
  joinLink: {
    alignItems: "center",
    paddingVertical: 4,
  },
  joinLinkText: {
    color: "#084a2f",
    fontSize: 13,
    fontWeight: "700",
    textDecorationLine: "underline",
  },
  footerVersion: {
    textAlign: "center",
    color: "#8c8273",
    fontSize: 11,
    marginTop: 4,
  },
});
