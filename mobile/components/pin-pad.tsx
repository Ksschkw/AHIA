import React, { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
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
  const inputRef = useRef<React.ElementRef<typeof TextInput>>(null);

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

  const handleNativeTextChange = (text: string) => {
    const cleaned = text.replace(/[^0-9]/g, "").slice(0, length);
    setPin(cleaned);
    if (cleaned.length === length) {
      onComplete(cleaned);
    }
  };

  return (
    <View style={styles.container}>
      {/* Hidden native input for hardware/software keyboard support */}
      <TextInput
        ref={inputRef}
        value={pin}
        onChangeText={handleNativeTextChange}
        keyboardType="number-pad"
        maxLength={length}
        secureTextEntry
        style={styles.hiddenInput}
        editable={!disabled && !loading}
      />

      {/* Visual PIN digit boxes */}
      <Pressable
        style={styles.boxesRow}
        onPress={() => inputRef.current?.focus()}
        accessibilityLabel="Security PIN digits"
        accessibilityRole="button"
      >
        {Array.from({ length }).map((_, idx) => {
          const isFilled = idx < pin.length;
          const isCurrent = idx === pin.length;
          return (
            <View
              key={idx}
              style={[
                styles.box,
                isFilled && styles.boxFilled,
                isCurrent && styles.boxCurrent,
                Boolean(error) && styles.boxError,
              ]}
            >
              {isFilled ? (
                <View style={styles.dotFilled} />
              ) : isCurrent ? (
                <View style={styles.cursorBar} />
              ) : null}
            </View>
          );
        })}
      </Pressable>

      <Text style={styles.tapHint}>Tap boxes for device keyboard or use keypad below</Text>

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
    paddingVertical: 8,
    width: "100%",
  },
  hiddenInput: {
    position: "absolute",
    width: 1,
    height: 1,
    opacity: 0,
  },
  boxesRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 6,
  },
  box: {
    width: 48,
    height: 52,
    marginHorizontal: 6,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: "#334155",
    backgroundColor: "#0f172a",
    alignItems: "center",
    justifyContent: "center",
  },
  boxCurrent: {
    borderColor: "#4ade80",
    backgroundColor: "#13231b",
  },
  boxFilled: {
    borderColor: "#22c55e",
    backgroundColor: "#0d281e",
  },
  boxError: {
    borderColor: "#f87171",
    backgroundColor: "rgba(248, 113, 113, 0.15)",
  },
  dotFilled: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: "#4ade80",
  },
  cursorBar: {
    width: 2,
    height: 20,
    backgroundColor: "#4ade80",
    borderRadius: 1,
  },
  tapHint: {
    color: "#64748b",
    fontSize: 11,
    marginBottom: 12,
    textAlign: "center",
  },
  loadingBox: {
    flexDirection: "row",
    alignItems: "center",
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
    marginLeft: 8,
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
    maxWidth: 290,
  },
  keypadRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginVertical: 4,
  },
  keyBtn: {
    flex: 1,
    height: 52,
    marginHorizontal: 5,
    borderRadius: 12,
    backgroundColor: "#1e293b",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#334155",
  },
  keyBtnDisabled: {
    opacity: 0.4,
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
    fontWeight: "700",
  },
});
