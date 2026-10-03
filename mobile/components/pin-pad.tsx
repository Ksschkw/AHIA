import React, { useState, useEffect } from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import * as Haptics from "expo-haptics";
import { BackspaceIcon } from "@/components/icons";

interface PinPadProps {
  length?: number;
  onComplete: (pin: string) => void;
  error?: string | null;
  disabled?: boolean;
  loading?: boolean;
  loadingMessage?: string;
  onClear?: () => void;
}

export function PinPad({
  length = 4,
  onComplete,
  error,
  disabled = false,
  loading = false,
  loadingMessage = "Verifying...",
  onClear,
}: PinPadProps) {
  const [pin, setPin] = useState("");

  useEffect(() => {
    if (error) {
      setPin("");
    }
  }, [error]);

  const handleDigit = (digit: string) => {
    if (disabled || loading || pin.length >= length) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const nextPin = pin + digit;
    setPin(nextPin);
    if (nextPin.length === length) {
      onComplete(nextPin);
    }
  };

  const handleBackspace = () => {
    if (disabled || loading || pin.length === 0) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setPin((curr) => curr.slice(0, -1));
  };

  const handleClear = () => {
    if (disabled || loading || pin.length === 0) return;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setPin("");
    onClear?.();
  };

  return (
    <View style={styles.container}>
      {/* Visual PIN Dots */}
      <View style={styles.dotsRow}>
        {Array.from({ length }).map((_, idx) => {
          const isFilled = idx < pin.length;
          return (
            <View
              key={idx}
              style={[
                styles.dot,
                isFilled && styles.dotFilled,
                Boolean(error) && styles.dotError,
              ]}
            />
          );
        })}
      </View>

      {loading ? (
        <View style={styles.loadingBox}>
          <ActivityIndicator size="small" color="#4ade80" />
          <Text style={styles.loadingText}>{loadingMessage}</Text>
        </View>
      ) : error ? (
        <Text style={styles.errorText}>{error}</Text>
      ) : null}

      {/* Numeric Keypad Grid */}
      <View style={styles.keypadGrid}>
        <View style={styles.keypadRow}>
          {["1", "2", "3"].map((num) => (
            <Pressable
              key={num}
              style={({ pressed }) => [
                styles.keyBtn,
                (disabled || loading) && styles.keyBtnDisabled,
                pressed && styles.keyBtnPressed,
              ]}
              onPress={() => handleDigit(num)}
              disabled={disabled || loading}
            >
              <Text style={styles.keyBtnText}>{num}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.keypadRow}>
          {["4", "5", "6"].map((num) => (
            <Pressable
              key={num}
              style={({ pressed }) => [
                styles.keyBtn,
                (disabled || loading) && styles.keyBtnDisabled,
                pressed && styles.keyBtnPressed,
              ]}
              onPress={() => handleDigit(num)}
              disabled={disabled || loading}
            >
              <Text style={styles.keyBtnText}>{num}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.keypadRow}>
          {["7", "8", "9"].map((num) => (
            <Pressable
              key={num}
              style={({ pressed }) => [
                styles.keyBtn,
                (disabled || loading) && styles.keyBtnDisabled,
                pressed && styles.keyBtnPressed,
              ]}
              onPress={() => handleDigit(num)}
              disabled={disabled || loading}
            >
              <Text style={styles.keyBtnText}>{num}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.keypadRow}>
          <Pressable
            style={({ pressed }) => [
              styles.keyBtn,
              styles.actionKeyBtn,
              pressed && styles.keyBtnPressed,
            ]}
            onPress={handleClear}
            disabled={disabled || loading || pin.length === 0}
          >
            <Text style={styles.actionKeyText}>Clear</Text>
          </Pressable>

          <Pressable
            style={({ pressed }) => [
              styles.keyBtn,
              (disabled || loading) && styles.keyBtnDisabled,
              pressed && styles.keyBtnPressed,
            ]}
            onPress={() => handleDigit("0")}
            disabled={disabled || loading}
          >
            <Text style={styles.keyBtnText}>0</Text>
          </Pressable>

          <Pressable
            style={({ pressed }) => [
              styles.keyBtn,
              styles.actionKeyBtn,
              pressed && styles.keyBtnPressed,
            ]}
            onPress={handleBackspace}
            disabled={disabled || loading || pin.length === 0}
          >
            <BackspaceIcon size={22} color="#94a3b8" />
          </Pressable>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    paddingVertical: 12,
  },
  dotsRow: {
    flexDirection: "row",
    gap: 16,
    marginBottom: 16,
    justifyContent: "center",
  },
  dot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: "#4b5563",
    backgroundColor: "transparent",
  },
  dotFilled: {
    backgroundColor: "#4ade80",
    borderColor: "#4ade80",
  },
  dotError: {
    borderColor: "#f87171",
    backgroundColor: "rgba(248, 113, 113, 0.2)",
  },
  loadingBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 12,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "rgba(74, 222, 128, 0.1)",
  },
  loadingText: {
    color: "#4ade80",
    fontSize: 13,
    fontWeight: "600",
  },
  errorText: {
    color: "#f87171",
    fontSize: 13,
    fontWeight: "600",
    marginBottom: 12,
    textAlign: "center",
  },
  keypadGrid: {
    width: "100%",
    maxWidth: 280,
    gap: 10,
  },
  keypadRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
  },
  keyBtn: {
    flex: 1,
    height: 54,
    borderRadius: 27,
    backgroundColor: "#1e293b",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#334155",
  },
  keyBtnDisabled: {
    opacity: 0.5,
  },
  keyBtnPressed: {
    backgroundColor: "#334155",
    transform: [{ scale: 0.96 }],
  },
  keyBtnText: {
    color: "#f8fafc",
    fontSize: 22,
    fontWeight: "700",
  },
  actionKeyBtn: {
    backgroundColor: "#0f172a",
    borderColor: "#1e293b",
  },
  actionKeyText: {
    color: "#94a3b8",
    fontSize: 13,
    fontWeight: "600",
  },
});
