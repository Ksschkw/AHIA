import { useEffect } from "react";
import Animated, {
  Easing,
  useAnimatedProps,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import Svg, { Rect } from "react-native-svg";

/**
 * The mark, alive.
 *
 * The shape is the product's own - the four-square tile from `app/icon.svg`, drawn here in `react-native-svg`
 * so it can be animated rather than pasted in as a picture. Nothing about the geometry is invented: the
 * rounded green tile and the four squares, with two of them at lower opacity, are exactly what every screen
 * and every icon already carries.
 *
 * What moves is the **pairs**. One square on each diagonal breathes at a time, which reads as the four corners
 * taking turns - the mark's own two-tone idea, set in motion, rather than a decoration bolted onto it.
 */
const AnimatedRect = Animated.createAnimatedComponent(Rect);

export function AhiaMark({ size = 132 }: { size?: number }) {
  // The tile arrives with a spring, so it lands rather than appears.
  const tile = useSharedValue(0.6);
  useEffect(() => {
    tile.value = withSpring(1, { damping: 12, stiffness: 120 });
  }, [tile]);

  // Two breath rates, one for each diagonal pair: slow enough to notice, slow enough not to distract.
  const first = useSharedValue(1);
  const second = useSharedValue(1);
  useEffect(() => {
    const breathe = (value: typeof first, delay: number) => {
      value.value = withDelay(
        delay,
        withRepeat(
          withSequence(
            withTiming(0.45, { duration: 1400, easing: Easing.inOut(Easing.quad) }),
            withTiming(1, { duration: 1400, easing: Easing.inOut(Easing.quad) }),
          ),
          -1,
          false,
        ),
      );
    };
    breathe(first, 500);
    breathe(second, 1200);
  }, [first, second]);

  const tileStyle = useAnimatedStyle(() => ({
    transform: [{ scale: tile.value }],
    opacity: tile.value,
  }));
  const firstProps = useAnimatedProps(() => ({ opacity: first.value }));
  const secondProps = useAnimatedProps(() => ({ opacity: second.value }));

  return (
    <Animated.View style={tileStyle} accessible accessibilityLabel="AHIA">
      <Svg width={size} height={size} viewBox="0 0 24 24">
        <Rect x="1" y="1" width="22" height="22" rx="7" fill="#0b5d3b" />
        {/* The two bright corners breathe together, then the two dim ones. */}
        <AnimatedRect x="5" y="5" width="4" height="4" rx="1.2" fill="#ffffff" animatedProps={firstProps} />
        <AnimatedRect
          x="15"
          y="5"
          width="4"
          height="4"
          rx="1.2"
          fill="#ffffff"
          opacity={0.35}
          animatedProps={secondProps}
        />
        <AnimatedRect
          x="5"
          y="15"
          width="4"
          height="4"
          rx="1.2"
          fill="#ffffff"
          opacity={0.35}
          animatedProps={secondProps}
        />
        <AnimatedRect x="15" y="15" width="4" height="4" rx="1.2" fill="#ffffff" animatedProps={firstProps} />
      </Svg>
    </Animated.View>
  );
}
