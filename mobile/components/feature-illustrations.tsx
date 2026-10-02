import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import Svg, {
  Circle,
  Defs,
  G,
  LinearGradient,
  Path,
  Rect,
  Stop,
} from "react-native-svg";

/**
 * Adobe Illustrator-Grade Vector Object Models with Framer-Motion Style Physics.
 *
 * Each model renders dynamic 3D isometric vector art with continuous floating,
 * pulsing, and breathing physics driven by React Native Reanimated.
 */

// 1. Isometric Market Stall Model
export function StallModelIllustration() {
  const floatAnim = useSharedValue(0);
  const coinAnim = useSharedValue(0);

  useEffect(() => {
    floatAnim.value = withRepeat(
      withSequence(
        withTiming(-8, { duration: 1800 }),
        withTiming(0, { duration: 1800 }),
      ),
      -1,
      true,
    );
    coinAnim.value = withRepeat(
      withSequence(
        withTiming(-12, { duration: 1200 }),
        withTiming(4, { duration: 1200 }),
      ),
      -1,
      true,
    );
  }, [floatAnim, coinAnim]);

  const floatStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: floatAnim.value }],
  }));

  const coinStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: coinAnim.value }, { rotateZ: "-6deg" }],
  }));

  return (
    <View style={styles.modelContainer}>
      {/* Ambient Floor Shadow */}
      <Svg width={220} height={40} style={styles.floorShadow}>
        <Defs>
          <LinearGradient id="stallShadow" x1="0%" y1="0%" x2="100%" y2="0%">
            <Stop offset="0%" stopColor="#000000" stopOpacity="0" />
            <Stop offset="50%" stopColor="#000000" stopOpacity="0.35" />
            <Stop offset="100%" stopColor="#000000" stopOpacity="0" />
          </LinearGradient>
        </Defs>
        <Circle cx={110} cy={20} r={55} fill="url(#stallShadow)" />
      </Svg>

      {/* Floating 3D Vector Stall */}
      <Animated.View style={[styles.mainArtwork, floatStyle]}>
        <Svg width={220} height={180} viewBox="0 0 220 180">
          <Defs>
            <LinearGradient id="canopyGreen" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#10b981" />
              <Stop offset="100%" stopColor="#064e3b" />
            </LinearGradient>
            <LinearGradient id="canopyGold" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#fbbf24" />
              <Stop offset="100%" stopColor="#d97706" />
            </LinearGradient>
            <LinearGradient id="wallGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#1e293b" />
              <Stop offset="100%" stopColor="#0f172a" />
            </LinearGradient>
            <LinearGradient id="shelfGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <Stop offset="0%" stopColor="#334155" />
              <Stop offset="100%" stopColor="#1e293b" />
            </LinearGradient>
          </Defs>

          {/* Stall Base Frame */}
          <Path
            d="M40 90 L180 90 L195 155 L25 155 Z"
            fill="url(#wallGradient)"
            stroke="#334155"
            strokeWidth={2}
          />

          {/* Counter Top Surface */}
          <Path
            d="M20 90 L200 90 L185 106 L35 106 Z"
            fill="url(#shelfGradient)"
            stroke="#475569"
            strokeWidth={1.5}
          />

          {/* Counter Front Panel with Modern Slits */}
          <Rect x={45} y={114} width={130} height={32} rx={6} fill="#0f172a" />
          <Rect x={55} y={120} width={32} height={20} rx={4} fill="#059669" opacity={0.8} />
          <Rect x={95} y={120} width={32} height={20} rx={4} fill="#0284c7" opacity={0.8} />
          <Rect x={135} y={120} width={30} height={20} rx={4} fill="#d97706" opacity={0.8} />

          {/* 3D Stall Striped Canopy Roof */}
          <G>
            {/* Canopy Left Slant */}
            <Path d="M20 52 L50 20 L75 52 Z" fill="url(#canopyGreen)" />
            {/* Canopy Gold Stripe 1 */}
            <Path d="M50 20 L80 20 L95 52 L75 52 Z" fill="url(#canopyGold)" />
            {/* Canopy Green Stripe 2 */}
            <Path d="M80 20 L110 20 L115 52 L95 52 Z" fill="url(#canopyGreen)" />
            {/* Canopy Gold Stripe 3 */}
            <Path d="M110 20 L140 20 L135 52 L115 52 Z" fill="url(#canopyGold)" />
            {/* Canopy Green Stripe 4 */}
            <Path d="M140 20 L170 20 L155 52 L135 52 Z" fill="url(#canopyGreen)" />
            {/* Canopy Right Slant */}
            <Path d="M170 20 L200 52 L155 52 Z" fill="url(#canopyGold)" />

            {/* Scalloped Canopy Valance Edges */}
            <Path
              d="M20 52 Q32 64 45 52 Q58 64 70 52 Q82 64 95 52 Q108 64 120 52 Q132 64 145 52 Q158 64 170 52 Q185 64 200 52"
              fill="none"
              stroke="#fbbf24"
              strokeWidth={3}
            />
          </G>

          {/* Support Pillars */}
          <Rect x={36} y={52} width={5} height={38} fill="#94a3b8" />
          <Rect x={179} y={52} width={5} height={38} fill="#94a3b8" />

          {/* Cash Register / Terminal on Counter */}
          <Rect x={90} y={72} width={40} height={24} rx={4} fill="#1e293b" stroke="#38bdf8" strokeWidth={1.5} />
          <Rect x={98} y={76} width={24} height={10} rx={2} fill="#0ea5e9" opacity={0.9} />
          <Circle cx={110} cy={91} r={2} fill="#4ade80" />
        </Svg>
      </Animated.View>

      {/* Floating 3D Gold Coins */}
      <Animated.View style={[styles.floatingCoin, coinStyle]}>
        <Svg width={46} height={46} viewBox="0 0 46 46">
          <Defs>
            <LinearGradient id="coinGold" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#fef08a" />
              <Stop offset="50%" stopColor="#f59e0b" />
              <Stop offset="100%" stopColor="#b45309" />
            </LinearGradient>
          </Defs>
          <Circle cx={23} cy={23} r={20} fill="url(#coinGold)" stroke="#fef3c7" strokeWidth={2} />
          <Circle cx={23} cy={23} r={15} fill="none" stroke="#d97706" strokeWidth={1.5} />
          <Path d="M21 16 L25 16 M23 16 L23 30 M20 20 L26 20 M20 26 L26 26" stroke="#ffffff" strokeWidth={2} strokeLinecap="round" />
        </Svg>
      </Animated.View>
    </View>
  );
}

// 2. Offline Resilience 3D Vault & Sync Wave Model
export function OfflineVaultIllustration() {
  const pulseAnim = useSharedValue(1);
  const dialAnim = useSharedValue(0);

  useEffect(() => {
    pulseAnim.value = withRepeat(
      withSequence(
        withTiming(1.08, { duration: 1500 }),
        withTiming(1, { duration: 1500 }),
      ),
      -1,
      true,
    );
    dialAnim.value = withRepeat(
      withSequence(
        withTiming(45, { duration: 2000 }),
        withTiming(0, { duration: 2000 }),
      ),
      -1,
      true,
    );
  }, [pulseAnim, dialAnim]);

  const pulseStyle = useAnimatedStyle(() => ({
    transform: [{ scale: pulseAnim.value }],
  }));

  return (
    <View style={styles.modelContainer}>
      <Animated.View style={[styles.mainArtwork, pulseStyle]}>
        <Svg width={220} height={180} viewBox="0 0 220 180">
          <Defs>
            <LinearGradient id="vaultBody" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#1e293b" />
              <Stop offset="50%" stopColor="#0f172a" />
              <Stop offset="100%" stopColor="#020617" />
            </LinearGradient>
            <LinearGradient id="vaultRim" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#10b981" />
              <Stop offset="100%" stopColor="#047857" />
            </LinearGradient>
            <LinearGradient id="neonGlow" x1="0%" y1="0%" x2="100%" y2="0%">
              <Stop offset="0%" stopColor="#34d399" />
              <Stop offset="100%" stopColor="#059669" />
            </LinearGradient>
          </Defs>

          {/* Outer Sync Energy Wave Rings */}
          <Circle cx={110} cy={90} r={80} fill="none" stroke="#10b981" strokeWidth={1.5} opacity={0.2} strokeDasharray="6 8" />
          <Circle cx={110} cy={90} r={68} fill="none" stroke="#34d399" strokeWidth={1.5} opacity={0.35} strokeDasharray="4 6" />

          {/* Heavy Steel Vault Safe Body */}
          <Rect x={50} y={35} width={120} height={110} rx={22} fill="url(#vaultBody)" stroke="#334155" strokeWidth={3} />

          {/* Reinforced Corner Bolts */}
          <Circle cx={65} cy={50} r={4} fill="#64748b" />
          <Circle cx={155} cy={50} r={4} fill="#64748b" />
          <Circle cx={65} cy={130} r={4} fill="#64748b" />
          <Circle cx={155} cy={130} r={4} fill="#64748b" />

          {/* Center Rotating Wheel Dial */}
          <Circle cx={110} cy={90} r={34} fill="#0f172a" stroke="url(#vaultRim)" strokeWidth={4} />
          <Circle cx={110} cy={90} r={24} fill="#020617" stroke="#34d399" strokeWidth={2} />

          {/* 3 Spokes on Dial */}
          <Path d="M110 66 L110 114 M86 90 L134 90 M93 73 L127 107 M93 107 L127 73" stroke="#64748b" strokeWidth={2.5} />

          {/* Core Green Status Beacon */}
          <Circle cx={110} cy={90} r={10} fill="url(#neonGlow)" />
          <Path d="M106 90 L109 93 L115 87" fill="none" stroke="#ffffff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

          {/* Offline Resilient SQLite Emblem Badge */}
          <Rect x={76} y={124} width={68} height={16} rx={8} fill="#064e3b" stroke="#10b981" strokeWidth={1} />
        </Svg>
      </Animated.View>
    </View>
  );
}

// 3. WhatsApp Trade Quotes Holographic Receipt Model
export function TradeQuoteIllustration() {
  const receiptAnim = useSharedValue(0);
  const bubbleAnim = useSharedValue(0);

  useEffect(() => {
    receiptAnim.value = withRepeat(
      withSequence(
        withTiming(-6, { duration: 1600 }),
        withTiming(2, { duration: 1600 }),
      ),
      -1,
      true,
    );
    bubbleAnim.value = withRepeat(
      withSequence(
        withTiming(-10, { duration: 1300 }),
        withTiming(2, { duration: 1300 }),
      ),
      -1,
      true,
    );
  }, [receiptAnim, bubbleAnim]);

  const receiptStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: receiptAnim.value }, { rotateZ: "-3deg" }],
  }));

  const bubbleStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: bubbleAnim.value }, { rotateZ: "4deg" }],
  }));

  return (
    <View style={styles.modelContainer}>
      {/* Floating Digital Smart Receipt */}
      <Animated.View style={[styles.mainArtwork, receiptStyle]}>
        <Svg width={180} height={190} viewBox="0 0 180 190">
          <Defs>
            <LinearGradient id="receiptGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#f8fafc" />
              <Stop offset="100%" stopColor="#e2e8f0" />
            </LinearGradient>
            <LinearGradient id="barcodeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <Stop offset="0%" stopColor="#0f172a" />
              <Stop offset="100%" stopColor="#334155" />
            </LinearGradient>
          </Defs>

          {/* Receipt Body with Zig-Zag Top & Bottom */}
          <Path
            d="M25 15 L35 22 L45 15 L55 22 L65 15 L75 22 L85 15 L95 22 L105 15 L115 22 L125 15 L135 22 L145 15 L155 22 L155 165 L145 172 L135 165 L125 172 L115 165 L105 172 L95 165 L85 172 L75 165 L65 172 L55 165 L45 172 L35 165 L25 172 Z"
            fill="url(#receiptGrad)"
            stroke="#cbd5e1"
            strokeWidth={1.5}
          />

          {/* Receipt Header Pill */}
          <Rect x={45} y={35} width={90} height={14} rx={7} fill="#084a2f" />

          {/* Text Line Mockups */}
          <Rect x={45} y={60} width={55} height={6} rx={3} fill="#64748b" />
          <Rect x={115} y={60} width={20} height={6} rx={3} fill="#0f172a" />

          <Rect x={45} y={74} width={45} height={6} rx={3} fill="#94a3b8" />
          <Rect x={110} y={74} width={25} height={6} rx={3} fill="#0f172a" />

          <Rect x={45} y={88} width={60} height={6} rx={3} fill="#94a3b8" />
          <Rect x={115} y={88} width={20} height={6} rx={3} fill="#0f172a" />

          {/* Divider Dashed Line */}
          <Path d="M45 106 L135 106" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" />

          {/* Total Row */}
          <Rect x={45} y={116} width={40} height={8} rx={4} fill="#084a2f" />
          <Rect x={100} y={115} width={35} height={10} rx={4} fill="#059669" />

          {/* Barcode Strip */}
          <Path
            d="M48 138 h4 v16 h-4z M55 138 h2 v16 h-2z M60 138 h6 v16 h-6z M69 138 h2 v16 h-2z M74 138 h5 v16 h-5z M82 138 h3 v16 h-3z M88 138 h6 v16 h-6z M97 138 h2 v16 h-2z M102 138 h5 v16 h-5z M110 138 h3 v16 h-3z M116 138 h6 v16 h-6z M125 138 h4 v16 h-4z"
            fill="url(#barcodeGrad)"
          />
        </Svg>
      </Animated.View>

      {/* Floating 3D WhatsApp Speech Bubble */}
      <Animated.View style={[styles.floatingBubble, bubbleStyle]}>
        <Svg width={80} height={60} viewBox="0 0 80 60">
          <Defs>
            <LinearGradient id="waGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#25D366" />
              <Stop offset="100%" stopColor="#128C7E" />
            </LinearGradient>
          </Defs>
          <Path
            d="M12 8 C12 3.6 15.6 0 20 0 L68 0 C72.4 0 76 3.6 76 8 L76 36 C76 40.4 72.4 44 68 44 L28 44 L16 54 L17 44 L20 44 C15.6 44 12 40.4 12 36 Z"
            fill="url(#waGrad)"
          />
          {/* WhatsApp Double Checkmarks */}
          <Path
            d="M30 22 L36 28 L50 14 M40 28 L54 14"
            fill="none"
            stroke="#ffffff"
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </Svg>
      </Animated.View>
    </View>
  );
}

// 4. Role Shields & Business Security Lock Model
export function RoleShieldIllustration() {
  const shieldAnim = useSharedValue(0);
  const ringAnim = useSharedValue(1);

  useEffect(() => {
    shieldAnim.value = withRepeat(
      withSequence(
        withTiming(-7, { duration: 1700 }),
        withTiming(3, { duration: 1700 }),
      ),
      -1,
      true,
    );
    ringAnim.value = withRepeat(
      withSequence(
        withTiming(1.06, { duration: 1400 }),
        withTiming(1, { duration: 1400 }),
      ),
      -1,
      true,
    );
  }, [shieldAnim, ringAnim]);

  const shieldStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: shieldAnim.value }],
  }));

  const ringStyle = useAnimatedStyle(() => ({
    transform: [{ scale: ringAnim.value }],
  }));

  return (
    <View style={styles.modelContainer}>
      <Animated.View style={[styles.mainArtwork, shieldStyle]}>
        <Svg width={220} height={190} viewBox="0 0 220 190">
          <Defs>
            <LinearGradient id="shieldGold" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#fef08a" />
              <Stop offset="50%" stopColor="#f59e0b" />
              <Stop offset="100%" stopColor="#b45309" />
            </LinearGradient>
            <LinearGradient id="shieldCore" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#065f46" />
              <Stop offset="50%" stopColor="#064e3b" />
              <Stop offset="100%" stopColor="#022c22" />
            </LinearGradient>
            <LinearGradient id="lockSilver" x1="0%" y1="0%" x2="100%" y2="100%">
              <Stop offset="0%" stopColor="#e2e8f0" />
              <Stop offset="100%" stopColor="#94a3b8" />
            </LinearGradient>
          </Defs>

          {/* Outer Protective Heraldic Shield */}
          <Path
            d="M110 20 L175 48 C175 110 148 152 110 175 C72 152 45 110 45 48 Z"
            fill="url(#shieldGold)"
            stroke="#fef3c7"
            strokeWidth={3}
          />

          {/* Inner Emerald Security Plate */}
          <Path
            d="M110 32 L163 56 C163 108 141 142 110 162 C79 142 57 108 57 56 Z"
            fill="url(#shieldCore)"
          />

          {/* 3D Padlock Shackle */}
          <Path
            d="M94 88 V72 A16 16 0 0 1 126 72 V88"
            fill="none"
            stroke="url(#lockSilver)"
            strokeWidth={6}
            strokeLinecap="round"
          />

          {/* Padlock Body */}
          <Rect x={84} y={86} width={52} height={42} rx={10} fill="#f59e0b" stroke="#fef3c7" strokeWidth={2} />

          {/* 4 Security PIN Dials */}
          <Circle cx={95} cy={102} r={3} fill="#ffffff" />
          <Circle cx={105} cy={102} r={3} fill="#ffffff" />
          <Circle cx={115} cy={102} r={3} fill="#ffffff" />
          <Circle cx={125} cy={102} r={3} fill="#ffffff" />

          {/* Keyhole */}
          <Circle cx={110} cy={114} r={3} fill="#0f172a" />
          <Path d="M109 114 L111 114 L112 122 L108 122 Z" fill="#0f172a" />

          {/* Role Status Pills */}
          <Rect x={78} y={142} width={64} height={14} rx={7} fill="#10b981" />
        </Svg>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  modelContainer: {
    width: 220,
    height: 190,
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
  },
  floorShadow: {
    position: "absolute",
    bottom: 2,
  },
  mainArtwork: {
    alignItems: "center",
    justifyContent: "center",
  },
  floatingCoin: {
    position: "absolute",
    top: 15,
    right: 15,
    shadowColor: "#f59e0b",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.35,
    shadowRadius: 10,
    elevation: 6,
  },
  floatingBubble: {
    position: "absolute",
    top: 12,
    right: 5,
    shadowColor: "#25D366",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.35,
    shadowRadius: 10,
    elevation: 6,
  },
});
