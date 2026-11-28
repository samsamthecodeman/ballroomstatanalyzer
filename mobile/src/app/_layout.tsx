import React from "react";
import { Pressable, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { Stack, router } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { AccountProvider, useAccount } from "../accountContext";
import { Button, Note, usePalette } from "../ui";
function Frame() {
  const c = usePalette(),
    account = useAccount();
  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: c.bg }}
      edges={["top", "left", "right"]}
    >
      <StatusBar style={c.dark ? "light" : "dark"} />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Ballroom Stats Analyzer home"
        onPress={() => router.navigate("/")}
        style={{
          paddingHorizontal: 24,
          paddingVertical: 18,
          borderBottomWidth: 1,
          borderColor: c.line,
        }}
      >
        <Text style={{ color: c.ink, fontSize: 17, fontWeight: "700" }}>
          Ballroom Stats Analyzer
        </Text>
      </Pressable>
      {account.error ? (
        <View style={{ paddingHorizontal: 24 }}>
          <Note error>{account.error}</Note>
          <Button title="Dismiss" quiet onPress={account.dismissError} />
        </View>
      ) : null}
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: c.bg },
        }}
      />
    </SafeAreaView>
  );
}
export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AccountProvider>
        <Frame />
      </AccountProvider>
    </SafeAreaProvider>
  );
}
