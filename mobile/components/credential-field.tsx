import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

/**
 * A field, with a way to look at what was typed.
 *
 * Typing a password blind on a phone keyboard is how people end up locked out of their own account, and a
 * trader doing this once on a market street has no patience for a second attempt. The reveal is beside the
 * field because that is where the doubt happens.
 */
export function CredentialField({
  label,
  value,
  onChange,
  secret = false,
  keyboardType = "default",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  secret?: boolean;
  keyboardType?: "default" | "phone-pad" | "email-address";
  placeholder?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChange}
          secureTextEntry={secret && !revealed}
          keyboardType={keyboardType}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder={placeholder}
          accessibilityLabel={label}
        />
        {secret ? (
          <Pressable
            style={styles.reveal}
            onPress={() => setRevealed((current) => !current)}
            accessibilityRole="button"
            // Named for a screen reader, and for whoever is debugging the screen at midnight.
            accessibilityLabel={revealed ? `Hide ${label}` : `Show ${label}`}
          >
            <Text style={styles.revealText}>{revealed ? "Hide" : "Show"}</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 6 },
  label: { fontSize: 13, fontWeight: "700", color: "#5c5549" },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#d8d0c2",
    borderRadius: 10,
    paddingHorizontal: 14,
    minHeight: 52,
    fontSize: 16,
    backgroundColor: "#ffffff",
    color: "#1e1b16",
  },
  reveal: { paddingHorizontal: 10, minHeight: 52, justifyContent: "center" },
  revealText: { color: "#0b5d3b", fontWeight: "700", fontSize: 14 },
});
