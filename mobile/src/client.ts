import "react-native-url-polyfill/auto";
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Crypto from "expo-crypto";
import { createClient, processLock } from "@supabase/supabase-js";
import { chunkStorage, withoutProviderTokens } from "./chunkStorage";

// Browser previews use memory; installed apps use encrypted Keychain/Keystore storage.
const memory = new Map<string, string>();
export const storage =
  Platform.OS === "web"
    ? {
        getItem: async (key: string) => memory.get(key) ?? null,
        setItem: async (key: string, value: string) => {
          memory.set(key, value);
        },
        removeItem: async (key: string) => {
          memory.delete(key);
        },
      }
    : chunkStorage(SecureStore, Crypto.randomUUID);
const url = process.env.EXPO_PUBLIC_SUPABASE_URL || "";
const key = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";
if (key && !key.startsWith("sb_publishable_"))
  throw new Error(
    "Use a Supabase publishable key, never a secret or service-role key.",
  );
export const authConfigured = /^https:\/\//.test(url) && Boolean(key);
export const supabase = authConfigured
  ? createClient(url, key, {
      auth: {
        storage: {
          ...storage,
          setItem: (name: string, value: string) =>
            storage.setItem(name, withoutProviderTokens(value)),
        },
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
        flowType: "pkce",
        lock: processLock,
      },
    })
  : null;
