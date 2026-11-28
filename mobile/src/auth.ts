import { AppState, Linking, Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { supabase } from "./client";
import { callbackCode } from "./results";
import type { SavedDancer } from "./types";

export const AUTH_CALLBACK = "com.sammoran.ballroomstats://auth/callback";
WebBrowser.maybeCompleteAuthSession();
let signingIn = false;
const exchanges = new Map<string, Promise<void>>();
async function exchange(url: string) {
  if (!supabase) return;
  const code = callbackCode(url);
  if (!code) return;
  if (exchanges.has(code)) return exchanges.get(code);
  const task = (async () => {
    const { error } = await supabase!.auth.exchangeCodeForSession(code);
    if (error) throw error;
  })();
  exchanges.set(code, task);
  if (exchanges.size > 20) exchanges.delete(exchanges.keys().next().value!);
  return task;
}
export function listenForAuth(onError: (error: unknown) => void) {
  if (!supabase) return () => {};
  const handle = (url: string) => {
    exchange(url).catch(onError);
  };
  Linking.getInitialURL()
    .then((url) => {
      if (url) handle(url);
    })
    .catch(onError);
  const links = Linking.addEventListener("url", ({ url }) => handle(url));
  const refresh = (state: string | null | undefined) =>
    state === "active"
      ? supabase!.auth.startAutoRefresh()
      : supabase!.auth.stopAutoRefresh();
  refresh(AppState.currentState);
  const lifecycle = AppState.addEventListener("change", refresh);
  return () => {
    links.remove();
    lifecycle.remove();
    supabase!.auth.stopAutoRefresh();
  };
}
export async function signIn(provider: "google" | "apple") {
  if (!supabase)
    throw new Error("Sign-in is not available yet. You can browse as a guest.");
  if (Platform.OS === "web")
    throw new Error("Use an iOS or Android development build to sign in.");
  if (signingIn) return;
  signingIn = true;
  try {
    const { data, error } = await supabase.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: AUTH_CALLBACK,
        skipBrowserRedirect: true,
        scopes: provider === "apple" ? "name email" : "openid email profile",
      },
    });
    if (error) throw error;
    if (!data.url)
      throw new Error("The sign-in service did not return a login page.");
    const response = await WebBrowser.openAuthSessionAsync(
      data.url,
      AUTH_CALLBACK,
    );
    if (response.type === "success") await exchange(response.url);
  } finally {
    signingIn = false;
  }
}
export async function getSavedDancer(
  userId: string,
): Promise<SavedDancer | null> {
  const { data, error } = await supabase!
    .from("profiles")
    .select("dancer_name,dancer_aid")
    .eq("id", userId)
    .maybeSingle();
  if (error) throw error;
  return data?.dancer_name
    ? { name: data.dancer_name, aid: data.dancer_aid }
    : null;
}
export async function saveDancer(userId: string, dancer: SavedDancer) {
  const { error } = await supabase!
    .from("profiles")
    .upsert({ id: userId, dancer_name: dancer.name, dancer_aid: dancer.aid });
  if (error) throw error;
}
export async function signOut() {
  const { error } = await supabase!.auth.signOut();
  if (error) throw error;
}
