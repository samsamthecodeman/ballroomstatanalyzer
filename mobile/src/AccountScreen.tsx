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
import { deleteConfirmedAccount, signIn, signOut } from "./auth";
import type { DeletionConfirmation } from "./accountService";
import type { SavedDancer } from "./types";
import { errorMessage } from "./AnalysisScreen";
import { API_URL } from "./api";
import { Button, Heading, Input, Note, s, usePalette } from "./ui";
export default function AccountScreen({
  session,
  saved,
  ready,
  onUse,
  confirmation,
  preparing,
  onPrepareDeletion,
  onCancelDeletion,
}: {
  session: Session | null;
  saved: SavedDancer | null;
  ready: boolean;
  onUse: () => void;
  confirmation: DeletionConfirmation | null;
  preparing: boolean;
  onPrepareDeletion: () => Promise<void>;
  onCancelDeletion: () => void;
}) {
  const c = usePalette(),
    [working, setBusy] = useState(false),
    [error, setError] = useState(""),
    [typed, setTyped] = useState("");
  const busy = working || preparing;
  const activeConfirmation =
    confirmation?.userId === session?.user.id ? confirmation : null;
  async function prepareDeletion() {
    setBusy(true);
    setError("");
    onCancelDeletion();
    setTyped("");
    try {
      await onPrepareDeletion();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function finishDeletion() {
    if (!activeConfirmation) return;
    setBusy(true);
    setError("");
    try {
      await deleteConfirmedAccount(activeConfirmation, typed);
      onCancelDeletion();
      setTyped("");
    } catch (err) {
      setError(errorMessage(err));
      onCancelDeletion();
      setTyped("");
    } finally {
      setBusy(false);
    }
  }
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
          <Text style={[s.section, { color: c.red }]}>Delete account</Text>
          <Note>
            Deletion permanently removes your app account and saved dancer
            profile. Apple authorization is revoked first. Public competition
            results and your Google/Apple account remain unchanged.
          </Note>
          {activeConfirmation ? (
            <>
              <Note error>
                This cannot be undone. Type DELETE below, then confirm within
                five minutes.
              </Note>
              <Input
                accessibilityLabel="Type DELETE to confirm account deletion"
                placeholder="DELETE"
                autoCapitalize="characters"
                value={typed}
                editable={!busy}
                onChangeText={setTyped}
              />
              <Button
                title={busy ? "Deleting…" : "Permanently delete my account"}
                disabled={busy || typed !== "DELETE"}
                onPress={finishDeletion}
              />
              <View style={{ height: 12 }} />
              <Button
                title="Cancel deletion"
                quiet
                disabled={busy}
                onPress={() => {
                  onCancelDeletion();
                  setTyped("");
                }}
              />
            </>
          ) : (
            <Button
              title={busy ? "Working…" : "Verify identity to delete account"}
              quiet
              disabled={busy}
              onPress={prepareDeletion}
            />
          )}
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
        identical names. For Apple sign-in, we securely retain an authorization
        credential so we can revoke the app’s access when you delete your
        account.
      </Note>
      <Button
        title="Visit Ballroom Stats Analyzer"
        quiet
        onPress={() => Linking.openURL(API_URL)}
      />
    </ScrollView>
  );
}
