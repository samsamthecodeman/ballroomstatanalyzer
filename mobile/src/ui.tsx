import React from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useColorScheme,
  type TextInputProps,
} from "react-native";
export function usePalette() {
  const dark = useColorScheme() === "dark";
  return {
    dark,
    bg: dark ? "#090909" : "#fff",
    ink: dark ? "#fff" : "#101010",
    muted: dark ? "#aaa" : "#686868",
    line: dark ? "#383838" : "#d8d8d8",
    tint: dark ? "#181818" : "#f3f3f1",
    green: dark ? "#4ade80" : "#15803d",
    red: dark ? "#ff6476" : "#c91836",
  };
}
export function Button({
  title,
  onPress,
  disabled = false,
  quiet = false,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  quiet?: boolean;
}) {
  const c = usePalette();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        s.button,
        {
          opacity: disabled ? 0.4 : pressed ? 0.65 : 1,
          borderColor: c.ink,
          backgroundColor: quiet ? c.bg : c.ink,
        },
      ]}
    >
      <Text
        style={{ color: quiet ? c.ink : c.bg, fontWeight: "600", fontSize: 15 }}
      >
        {title}
      </Text>
    </Pressable>
  );
}
export function Choice({
  title,
  checked,
  onPress,
}: {
  title: string;
  checked: boolean;
  onPress: () => void;
}) {
  const c = usePalette();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      onPress={onPress}
      style={[
        s.choice,
        {
          borderColor: checked ? c.ink : c.line,
          backgroundColor: checked ? c.tint : c.bg,
        },
      ]}
    >
      <Text style={{ color: c.ink, fontSize: 14 }}>
        {checked ? "☑" : "☐"} {title}
      </Text>
    </Pressable>
  );
}
export function Input(props: TextInputProps) {
  const c = usePalette();
  return (
    <TextInput
      placeholderTextColor={c.muted}
      autoCorrect={false}
      {...props}
      style={[
        s.input,
        { borderColor: c.line, color: c.ink, backgroundColor: c.bg },
        props.style,
      ]}
    />
  );
}
export function Note({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  const c = usePalette();
  return (
    <Text
      accessibilityLiveRegion="polite"
      style={[s.note, { color: error ? c.red : c.muted }]}
    >
      {children}
    </Text>
  );
}
export function Heading({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  const c = usePalette();
  return (
    <View style={{ marginBottom: 24 }}>
      <Text accessibilityRole="header" style={[s.heading, { color: c.ink }]}>
        {title}
      </Text>
      {subtitle ? <Note>{subtitle}</Note> : null}
    </View>
  );
}
export const s = StyleSheet.create({
  screen: { flexGrow: 1, padding: 24, paddingBottom: 40 },
  heading: {
    fontSize: 42,
    lineHeight: 44,
    fontWeight: "700",
    letterSpacing: -1.8,
    marginBottom: 14,
  },
  section: { fontSize: 23, fontWeight: "600", marginTop: 28, marginBottom: 14 },
  note: { fontSize: 13, lineHeight: 20, marginVertical: 8 },
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    alignItems: "center",
  },
  button: {
    minHeight: 46,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  choice: {
    padding: 12,
    borderWidth: 1,
    minHeight: 44,
    justifyContent: "center",
  },
  input: {
    borderWidth: 1,
    minHeight: 48,
    paddingHorizontal: 14,
    fontSize: 16,
    marginBottom: 10,
  },
  card: { borderTopWidth: 1, paddingVertical: 18 },
  title: { fontSize: 17, lineHeight: 24, fontWeight: "600" },
  metric: { minWidth: "28%", flexGrow: 1, paddingVertical: 15 },
});
