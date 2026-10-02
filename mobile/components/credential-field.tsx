import * as Haptics from "expo-haptics";
import { useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
  View,
} from "react-native";

import {
  EyeIcon,
  EyeOffIcon,
  LockIcon,
  MailIcon,
  PhoneIcon,
  UserIcon,
} from "./icons";

/**
 * Modern High-Precision Credential Field.
 *
 * Designed to Apple/Fintech design standards with leading context icons,
 * high-contrast typography, interactive focus states, and one-tap secret reveal.
 */
export function CredentialField({
  label,
  value,
  onChange,
  secret = false,
  keyboardType = "default",
  placeholder,
  autoComplete,
  textContentType,
  importantForAutofill = "yes",
  leadingIcon,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  secret?: boolean;
  keyboardType?: "default" | "phone-pad" | "email-address";
  placeholder?: string;
  autoComplete?: TextInputProps["autoComplete"];
  textContentType?: TextInputProps["textContentType"];
  importantForAutofill?: TextInputProps["importantForAutofill"];
  leadingIcon?: React.ReactNode;
}) {
  const [revealed, setRevealed] = useState(false);
  const [isFocused, setIsFocused] = useState(false);

  // Derive sensible defaults for native password managers
  const derivedAutoComplete =
    autoComplete ??
    (secret ? "current-password" : keyboardType === "phone-pad" ? "tel" : "username");
  const derivedTextContentType =
    textContentType ??
    (secret ? "password" : keyboardType === "phone-pad" ? "telephoneNumber" : "username");

  // Determine leading icon based on field characteristics
  const renderIcon = () => {
    if (leadingIcon) return leadingIcon;
    const lower = label.toLowerCase();
    const iconColor = isFocused ? "#084a2f" : "#6e7681";

    if (secret || lower.includes("password")) {
      return <LockIcon size={18} color={iconColor} />;
    }
    if (lower.includes("phone") || keyboardType === "phone-pad") {
      return <PhoneIcon size={18} color={iconColor} />;
    }
    if (lower.includes("email") || keyboardType === "email-address") {
      return <MailIcon size={18} color={iconColor} />;
    }
    return <UserIcon size={18} color={iconColor} />;
  };

  const toggleReveal = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setRevealed((curr) => !curr);
  };

  return (
    <View style={styles.container}>
      <Text style={[styles.label, isFocused && styles.labelFocused]}>{label}</Text>
      <View
        style={[
          styles.inputContainer,
          isFocused && styles.inputContainerFocused,
          value.length > 0 && !isFocused && styles.inputContainerFilled,
        ]}
      >
        <View style={[styles.iconWrap, isFocused && styles.iconWrapFocused]}>
          {renderIcon()}
        </View>

        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChange}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          secureTextEntry={secret && !revealed}
          keyboardType={keyboardType}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder={placeholder}
          placeholderTextColor="#9ca3af"
          accessibilityLabel={label}
          autoComplete={derivedAutoComplete}
          textContentType={derivedTextContentType}
          importantForAutofill={importantForAutofill}
        />

        {secret && (
          <Pressable
            style={styles.revealButton}
            onPress={toggleReveal}
            accessibilityRole="button"
            accessibilityLabel={revealed ? `Hide ${label}` : `Show ${label}`}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
          >
            {revealed ? (
              <EyeOffIcon size={18} color="#084a2f" />
            ) : (
              <EyeIcon size={18} color="#6e7681" />
            )}
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 6,
    marginBottom: 2,
  },
  label: {
    fontSize: 13,
    fontWeight: "700",
    color: "#475569",
    letterSpacing: 0.1,
  },
  labelFocused: {
    color: "#084a2f",
  },
  inputContainer: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: "#e2e8f0",
    paddingHorizontal: 12,
    minHeight: 56,
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 6,
    elevation: 2,
  },
  inputContainerFilled: {
    borderColor: "#cbd5e1",
    backgroundColor: "#fcfdfe",
  },
  inputContainerFocused: {
    borderColor: "#084a2f",
    backgroundColor: "#ffffff",
    shadowColor: "#084a2f",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 4,
  },
  iconWrap: {
    width: 32,
    height: 32,
    borderRadius: 10,
    backgroundColor: "#f1f5f9",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 10,
  },
  iconWrapFocused: {
    backgroundColor: "rgba(8, 74, 47, 0.1)",
  },
  input: {
    flex: 1,
    fontSize: 16,
    color: "#0f172a",
    fontWeight: "500",
    paddingVertical: 12,
  },
  revealButton: {
    padding: 8,
    borderRadius: 10,
    backgroundColor: "#f8fafc",
    alignItems: "center",
    justifyContent: "center",
    marginLeft: 6,
  },
});
