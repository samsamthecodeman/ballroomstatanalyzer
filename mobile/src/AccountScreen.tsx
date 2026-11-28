import React, { useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Platform,
  ScrollView,
  Text,
  View,
} from "react-native";
import * as AppleAuthentication from "expo-apple-authentication";
import type { Session } from "@supabase/supabase-js";
import { authConfigured } from "./client";
import { signIn, signOut } from "./auth";
import type { SavedDancer } from "./types";
import { errorMessage } from "./AnalysisScreen";
import { API_URL } from "./api";
import { Button, Heading, Note, s, usePalette } from "./ui";
export default function AccountScreen({
  session,
  saved,
  ready,
  onUse,
}: {
  session: Session | null;
  saved: SavedDancer | null;
  ready: boolean;
  onUse: () => void;
}) {
  const c = usePalette(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function login(provider: "google" | "apple") {
    setBusy(true);
    setError("");
    try {
      await signIn(provider);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <ScrollView contentContainerStyle={s.screen}>
      <Heading
        title="Your dance story."
        subtitle="Sign in to keep your dancer profile across devices. Public results are always available as a guest."
      />
      {!ready ? (
        <ActivityIndicator color={c.ink} />
      ) : session ? (
        <>
          <Text style={[s.title, { color: c.ink }]}>
            {session.user.email || "Signed in"}
          </Text>
          <Note>
            {saved
              ? `Saved dancer: ${saved.name}`
              : "Run an analysis and tap Save first dancer to my account."}
          </Note>
          {saved && <Button title="Analyze my saved dancer" onPress={onUse} />}
          <View style={{ height: 14 }} />
          <Button
            title="Sign out"
            quiet
            disabled={busy}
            onPress={() => {
              setBusy(true);
              signOut()
                .catch((err) => setError(errorMessage(err)))
                .finally(() => setBusy(false));
            }}
          />
        </>
      ) : (
        <>
          <Button
            title="Continue with Google"
            disabled={busy || !authConfigured}
            quiet
            onPress={() => login("google")}
          />
          <View style={{ height: 12 }} />
          {Platform.OS === "ios" ? (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={
                AppleAuthentication.AppleAuthenticationButtonType.CONTINUE
              }
              buttonStyle={
                c.dark
                  ? AppleAuthentication.AppleAuthenticationButtonStyle.WHITE
                  : AppleAuthentication.AppleAuthenticationButtonStyle.BLACK
              }
              cornerRadius={0}
              style={{
                height: 48,
                width: "100%",
                opacity: busy || !authConfigured ? 0.4 : 1,
              }}
              onPress={() => {
                if (!busy && authConfigured) login("apple");
              }}
            />
          ) : (
            <Button
              title="Continue with Apple"
              disabled={busy || !authConfigured}
              onPress={() => login("apple")}
            />
          )}
          {!authConfigured && (
            <Note>
              Sign-in is not available yet. You can use all public results as a
              guest.
            </Note>
          )}
          <Note>
            Sign-in opens Google or Apple in your system browser. An account
            does not verify ownership of a public competition name.
          </Note>
        </>
      )}
      {error ? <Note error>{error}</Note> : null}
      <Text style={[s.section, { color: c.ink }]}>About your data</Text>
      <Note>
        Competition results are public. Your account stores your login identity
        and your chosen dancer name/ID. Public results may include people with
        identical names.
      </Note>
      <Button
        title="Visit Ballroom Stats Analyzer"
        quiet
        onPress={() => Linking.openURL(API_URL)}
      />
    </ScrollView>
  );
}
