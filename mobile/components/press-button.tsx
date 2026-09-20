import * as Haptics from "expo-haptics";
import { type ReactNode } from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from "react-native-reanimated";

/**
 * A button that answers the thumb.
 *
 * On a phone, a tap that produces no physical response feels broken - a trader presses twice and sends
 * something twice. So there are two answers: a short haptic, and a spring that presses the button down. Both
 * are on the UI thread, so neither waits for JavaScript to notice the finger.
 *
 * `tone` distinguishes the one action that moves forward from the one that only offers a choice, using the
 * product's own green and nothing else.
 */
const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

export function PressButton({
  label,
  onPress,
  tone = "primary",
  disabled = false,
}: {
  label: string;
  onPress: () => void;
  tone?: "primary" | "outline";
  disabled?: boolean;
}) {
  const pressed = useSharedValue(1);
  const style = useAnimatedStyle(() => ({ transform: [{ scale: pressed.value }] }));

  return (
    <AnimatedPressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      style={[style, tone === "primary" ? styles.primary : styles.outline, disabled ? styles.disabled : null]}
      onPressIn={() => {
        pressed.value = withSpring(0.96, { damping: 18, stiffness: 300 });
      }}
      onPressOut={() => {
        pressed.value = withSpring(1, { damping: 14, stiffness: 220 });
      }}
      onPress={() => {
        // A tap that lands should be felt. Deliberately a light impact: a trader presses this dozens of times a
        // day, and a heavy one becomes a reason to turn the feature off.
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress();
      }}
    >
      <Text style={tone === "primary" ? styles.primaryText : styles.outlineText}>{label}</Text>
    </AnimatedPressable>
  );
}

const styles = StyleSheet.create({
  primary: {
    minHeight: 56,
    borderRadius: 14,
    backgroundColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  outline: {
    minHeight: 56,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: "#0b5d3b",
    alignItems: "center",
    justifyContent: "center",
  },
  disabled: { opacity: 0.45 },
  primaryText: { color: "#ffffff", fontSize: 17, fontWeight: "700" },
  outlineText: { color: "#0b5d3b", fontSize: 17, fontWeight: "700" },
});
