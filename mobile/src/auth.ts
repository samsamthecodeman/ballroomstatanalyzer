import { AppState, Linking, Platform } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { storage, supabase } from "./client";
import { accountAction, type DeletionConfirmation } from "./accountService";
import { deletionFlow } from "./deletionFlow";
import { callbackCode } from "./results";
import type { SavedDancer } from "./types";

export const AUTH_CALLBACK = "com.sammoran.ballroomstats://auth/callback";
WebBrowser.maybeCompleteAuthSession();
let signingIn = false;
const exchanges = new Map<string, Promise<string>>();
const pendingProviderKey = "bsa-pending-oauth-provider";
async function exchange(url: string) {
  if (!supabase) return;
  const code = callbackCode(url);
  if (!code) return;
  if (exchanges.has(code)) return exchanges.get(code);
  const task = (async () => {
    const { data, error } = await supabase!.auth.exchangeCodeForSession(code);
    if (error) throw error;
    if (!data.session) throw new Error("Sign-in did not return a session.");
    const pending = await storage.getItem(pendingProviderKey);
    try {
      const provider = pending ? JSON.parse(pending) : null;
      if (
        provider?.name === "apple" &&
        provider.started > Date.now() - 10 * 60000 &&
        data.session.provider_refresh_token
      ) {
        await accountAction({
          action: "save-apple-token",
          token: data.session.provider_refresh_token,
        });
      }
    } finally {
      await storage.removeItem(pendingProviderKey);
    }
    return data.session.user.id;
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
  if (signingIn) throw new Error("A sign-in is already running.");
  signingIn = true;
  try {
    await storage.setItem(
      pendingProviderKey,
      JSON.stringify({ name: provider, started: Date.now() }),
    );
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
    if (response.type === "success") return await exchange(response.url);
    return null;
  } finally {
    signingIn = false;
    await storage.removeItem(pendingProviderKey);
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
const deletion = deletionFlow({
  reauthenticate: signIn,
  prepare: () =>
    accountAction<DeletionConfirmation>({ action: "prepare-delete" }),
  currentUser: async () => {
    const { data, error } = await supabase!.auth.getUser();
    return error ? null : data.user?.id || null;
  },
  remove: (confirmation) =>
    accountAction<{ deleted: boolean }>({
      action: "delete",
      confirm: "DELETE",
      confirmation,
    }),
  // This SDK removes the local session before its network sign-out request.
  signOut: async () => {
    await supabase!.auth.signOut({ scope: "local" });
  },
});
export const prepareAccountDeletion = deletion.prepare;
export const deleteConfirmedAccount = deletion.finish;
