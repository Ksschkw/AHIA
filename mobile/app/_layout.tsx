import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Pressable, StyleSheet, Text, View } from "react-native";

/**
 * Root frame and Error Boundary for AHIA mobile.
 *
 * Catches unhandled runtime exceptions gracefully so that device errors or
 * profile switching never crash with Android's "AHIA keeps stopping" dialog.
 */

export function ErrorBoundary({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <View style={styles.errorContainer}>
      <Text style={styles.errorBrand}>AHIA</Text>
      <Text style={styles.errorTitle}>Something went wrong</Text>
      <Text style={styles.errorMessage}>
        {error.message || "An unexpected error occurred while loading your shop."}
      </Text>
      <Pressable style={styles.errorButton} onPress={retry}>
        <Text style={styles.errorButtonText}>Reload Shop</Text>
      </Pressable>
    </View>
  );
}

export default function Root() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: "#fbf7f0" },
        }}
      />
    </>
  );
}

const styles = StyleSheet.create({
  errorContainer: {
    flex: 1,
    backgroundColor: "#fbf7f0",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  errorBrand: {
    fontSize: 28,
    fontWeight: "900",
    color: "#084a2f",
    letterSpacing: -0.5,
    marginBottom: 16,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: "700",
    color: "#1e1b16",
    marginBottom: 8,
  },
  errorMessage: {
    fontSize: 14,
    color: "#5c5549",
    textAlign: "center",
    marginBottom: 24,
    lineHeight: 20,
  },
  errorButton: {
    backgroundColor: "#084a2f",
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  errorButtonText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 15,
  },
});
