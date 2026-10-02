import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeInUp,
  FadeOut,
} from "react-native-reanimated";

import { AhiaMark } from "@/components/ahia-mark";
import {
  OfflineVaultIllustration,
  RoleShieldIllustration,
  StallModelIllustration,
  TradeQuoteIllustration,
} from "@/components/feature-illustrations";
import { restoreSession } from "@/lib/api";

interface SlideItem {
  id: string;
  badge: string;
  title: string;
  subtitle: string;
  illustration: () => React.ReactNode;
}

const SLIDES: SlideItem[] = [
  {
    id: "stall",
    badge: "BUILT FOR NIGERIAN MARKETS",
    title: "Your Entire Stall in Your Pocket",
    subtitle:
      "Manage shelf items, multi-tier normal & wholesale prices, and lightning fast customer tabs from anywhere.",
    illustration: () => <StallModelIllustration />,
  },
  {
    id: "offline",
    badge: "100% OFFLINE RESILIENT",
    title: "Zero Network? Never Lose a Sale",
    subtitle:
      "Record counter sales, add goods, create categories completely offline. Everything syncs quietly when connectivity returns.",
    illustration: () => <OfflineVaultIllustration />,
  },
  {
    id: "lists",
    badge: "INSTANT TRADE QUOTES",
    title: "Turn WhatsApp Chats into Priced Lists",
    subtitle:
      "Paste customer messages, price lines with one tap, calculate margins, and send waybill receipts straight to WhatsApp.",
    illustration: () => <TradeQuoteIllustration />,
  },
  {
    id: "security",
    badge: "ROLE CONTROLS & OWNER PIN",
    title: "Total Protection for Your Business",
    subtitle:
      "Separate sales apprentices from sensitive financial numbers. Lock profit margins and store settings behind your 4-digit Owner PIN.",
    illustration: () => <RoleShieldIllustration />,
  },
];

/**
 * The front door of AHIA Mobile.
 *
 * Automatically restores active sessions from SecureStore without requiring the
 * trader to log in again on app reopen.
 * Features Adobe Illustrator-grade 3D vector object models, Framer Motion-style physics,
 * and tactile bubbly curved buttons.
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

  // Slideshow auto-advance every 5 seconds
  useEffect(() => {
    if (checkingAuth) return;
    const timer = setInterval(() => {
      setActiveSlide((prev) => (prev + 1) % SLIDES.length);
    }, 5000);

    return () => clearInterval(timer);
  }, [checkingAuth]);

  const handleSelectSlide = (idx: number) => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setActiveSlide(idx);
  };

  if (checkingAuth) {
    return (
      <View style={styles.splashScreen}>
        <LinearGradient
          colors={["#031c12", "#084a2f", "#031c12"]}
          style={StyleSheet.absoluteFill}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
        />
        <Animated.View entering={FadeIn.duration(400)} style={styles.splashCenter}>
          <AhiaMark />
          <Text style={styles.splashTitle}>AHIA</Text>
          <Text style={styles.splashTagline}>The Operating System for Nigerian Markets</Text>
          <ActivityIndicator color="#4ade80" size="small" style={{ marginTop: 24 }} />
        </Animated.View>
      </View>
    );
  }

  const current = SLIDES[activeSlide];

  return (
    <LinearGradient
      colors={["#02180e", "#063824", "#031e13", "#010f09"]}
      style={styles.screen}
      start={{ x: 0, y: 0 }}
      end={{ x: 0.8, y: 1 }}
    >
      {/* Top Header Badge */}
      <Animated.View entering={FadeInDown.duration(400)} style={styles.topHeader}>
        <View style={styles.brandRow}>
          <AhiaMark />
          <View style={styles.brandTextWrap}>
            <Text style={styles.brandName}>AHIA</Text>
            <Text style={styles.brandTag}>TRADE OS</Text>
          </View>
        </View>
      </Animated.View>

      {/* Main Presentation Slideshow */}
      <View style={styles.presentationCard}>
        {/* Dynamic Vector Object Model Showcase */}
        <Animated.View
          key={`model-${current.id}`}
          entering={FadeInDown.springify().damping(14)}
          exiting={FadeOut.duration(200)}
          style={styles.illustrationWrap}
        >
          {current.illustration()}
        </Animated.View>

        {/* Feature Narrative & Details */}
        <Animated.View
          key={`text-${current.id}`}
          entering={FadeInUp.springify().damping(15)}
          exiting={FadeOut.duration(150)}
          style={styles.slideCopy}
        >
          <View style={styles.badgePill}>
            <Text style={styles.badgeText}>{current.badge}</Text>
          </View>

          <Text style={styles.headlineText}>{current.title}</Text>
          <Text style={styles.descriptionText}>{current.subtitle}</Text>
        </Animated.View>

        {/* Interactive Indicator Pills */}
        <View style={styles.indicatorRow}>
          {SLIDES.map((s, idx) => (
            <Pressable
              key={s.id}
              onPress={() => handleSelectSlide(idx)}
              style={styles.indicatorHitSlop}
            >
              <View
                style={[
                  styles.indicatorPill,
                  activeSlide === idx && styles.indicatorPillActive,
                ]}
              />
            </Pressable>
          ))}
        </View>
      </View>

      {/* Tactile Bubbly Action Buttons */}
      <View style={styles.bottomSheet}>
        {/* Primary Tactile Bubbly Button */}
        <Pressable
          style={({ pressed }) => [
            styles.bubblyButtonPrimary,
            pressed && styles.bubblyButtonPressed,
          ]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            router.push("/sign-in");
          }}
        >
          <LinearGradient
            colors={["#10b981", "#059669", "#047857"]}
            style={styles.bubblyButtonGradient}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
          >
            <Text style={styles.bubblyButtonTextPrimary}>Log in to your stall</Text>
          </LinearGradient>
        </Pressable>

        {/* Secondary Tactile Bubbly Button */}
        <Pressable
          style={({ pressed }) => [
            styles.bubblyButtonSecondary,
            pressed && styles.bubblyButtonPressed,
          ]}
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            router.push("/register");
          }}
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
  splashScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  splashCenter: {
    alignItems: "center",
    padding: 24,
  },
  splashTitle: {
    fontSize: 34,
    fontWeight: "900",
    color: "#ffffff",
    letterSpacing: 2,
    marginTop: 16,
  },
  splashTagline: {
    fontSize: 14,
    color: "#a7f3d0",
    marginTop: 6,
    textAlign: "center",
  },
  screen: {
    flex: 1,
    paddingTop: 48,
    paddingBottom: 24,
    paddingHorizontal: 20,
    justifyContent: "space-between",
  },
  topHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(6, 78, 59, 0.45)",
    paddingVertical: 6,
    paddingHorizontal: 16,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(52, 211, 153, 0.25)",
  },
  brandTextWrap: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 5,
  },
  brandName: {
    fontSize: 16,
    fontWeight: "900",
    color: "#ffffff",
    letterSpacing: 1.2,
  },
  brandTag: {
    fontSize: 9,
    fontWeight: "800",
    color: "#34d399",
    letterSpacing: 0.5,
  },
  presentationCard: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 10,
  },
  illustrationWrap: {
    alignItems: "center",
    justifyContent: "center",
    height: 190,
    marginBottom: 16,
  },
  slideCopy: {
    alignItems: "center",
    paddingHorizontal: 16,
  },
  badgePill: {
    backgroundColor: "rgba(52, 211, 153, 0.16)",
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "rgba(52, 211, 153, 0.3)",
    marginBottom: 12,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: "800",
    color: "#34d399",
    letterSpacing: 0.8,
  },
  headlineText: {
    fontSize: 24,
    fontWeight: "900",
    color: "#ffffff",
    textAlign: "center",
    letterSpacing: -0.4,
    marginBottom: 8,
    lineHeight: 30,
  },
  descriptionText: {
    fontSize: 13,
    color: "#94a3b8",
    textAlign: "center",
    lineHeight: 19,
    maxWidth: 320,
  },
  indicatorRow: {
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 20,
  },
  indicatorHitSlop: {
    padding: 6,
  },
  indicatorPill: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "rgba(255, 255, 255, 0.2)",
  },
  indicatorPillActive: {
    width: 24,
    backgroundColor: "#34d399",
  },
  bottomSheet: {
    gap: 12,
    paddingTop: 8,
  },
  bubblyButtonPrimary: {
    height: 56,
    borderRadius: 28,
    overflow: "hidden",
    shadowColor: "#10b981",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 16,
    elevation: 8,
  },
  bubblyButtonGradient: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
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
  bubblyButtonSecondary: {
    height: 56,
    borderRadius: 28,
    backgroundColor: "rgba(255, 255, 255, 0.08)",
    borderWidth: 1.5,
    borderColor: "rgba(255, 255, 255, 0.2)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  bubblyButtonTextSecondary: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "700",
  },
  joinLink: {
    alignItems: "center",
    paddingVertical: 6,
  },
  joinLinkText: {
    color: "#a7f3d0",
    fontSize: 12,
    fontWeight: "600",
  },
  footerVersion: {
    color: "#475569",
    fontSize: 11,
    textAlign: "center",
    marginTop: 2,
    fontWeight: "500",
  },
});
