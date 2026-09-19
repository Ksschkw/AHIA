import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

/**
 * The frame every screen sits in.
 *
 * Deliberately almost empty: the web app's shell - the rail, the bottom bar, the pinned destinations - is
 * where those decisions live, and this is the phone's own frame rather than a second copy of that one.
 */
export default function Root() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: "#f7f3ec" },
        }}
      />
    </>
  );
}
