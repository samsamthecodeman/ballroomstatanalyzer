import React from "react";
import { Text } from "react-native";
import { Tabs } from "expo-router";
import { usePalette } from "../../ui";
export default function TabLayout() {
  const c = usePalette();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: c.ink,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: { backgroundColor: c.bg, borderTopColor: c.line },
        sceneStyle: { backgroundColor: c.bg },
      }}
    >
      {[
        ["index", "Analyze"],
        ["rankings", "Rankings"],
        ["explore", "Explore"],
        ["account", "Account"],
      ].map(([name, title], index) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title,
            tabBarIcon: ({ color }) => (
              <Text style={{ color, fontSize: 16, fontWeight: "600" }}>
                0{index + 1}
              </Text>
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
