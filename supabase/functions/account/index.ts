import { createClient } from "@supabase/supabase-js";
import { decodeJwt } from "jose";
import { AccountError, accountHandler } from "./core.ts";
import { appleClient } from "./apple.ts";
import { tokenVault } from "./vault.ts";
const env = (key: string) => Deno.env.get(key) || "";
const admin = createClient(
  env("SUPABASE_URL"),
  env("SUPABASE_SERVICE_ROLE_KEY"),
  {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      fetch: (input, init) =>
        fetch(input, { ...init, signal: AbortSignal.timeout(12000) }),
    },
  },
);
const handler = accountHandler({
  async authenticate(token) {
    // getUser verifies the signature/expiry AND confirms that the account still exists.
    const { data, error } = await admin.auth.getUser(token);
    if (error || !data.user) {
      throw new AccountError(401, "unauthorized", "Sign in again.");
    }
    const claims = decodeJwt(token);
    if (claims.sub !== data.user.id || claims.role !== "authenticated") {
      throw new AccountError(401, "unauthorized", "Sign in again.");
    }
    const identities = data.user.identities?.filter((i) =>
      i.provider === "apple"
    ) || [];
    const amr = Array.isArray(claims.amr) ? claims.amr : [];
    return {
      id: data.user.id,
      sessionId: typeof claims.session_id === "string" ? claims.session_id : "",
      oauthAt: Math.max(
        0,
        ...amr.filter((a) =>
          a && a.method === "oauth" && typeof a.timestamp === "number"
        ).map((a) => a.timestamp),
      ),
      hasApple: identities.length > 0 ||
        data.user.app_metadata.providers?.includes("apple") === true,
      appleSubjects: identities.map((i) => i.identity_data?.sub).filter((
        s,
      ): s is string => typeof s === "string" && s.length > 0),
    };
  },
  async rpc(user, action, values = {}) {
    const { data, error } = await admin.rpc("account_security", {
      p_user: user,
      p_action: action,
      p_data: values,
    });
    if (error) throw new Error("Account database operation failed");
    return data;
  },
  apple: appleClient(() => ({
    clientId: env("APPLE_CLIENT_ID"),
    teamId: env("APPLE_TEAM_ID"),
    keyId: env("APPLE_KEY_ID"),
    privateKeyBase64: env("APPLE_PRIVATE_KEY_BASE64"),
  })),
  vault: {
    encrypt: (user, subject, token) =>
      tokenVault(
        JSON.parse(env("ACCOUNT_TOKEN_KEYRING") || "{}"),
        env("ACCOUNT_TOKEN_ACTIVE_KEY"),
      ).encrypt(user, subject, token),
    decrypt: (user, subject, token) =>
      tokenVault(
        JSON.parse(env("ACCOUNT_TOKEN_KEYRING") || "{}"),
        env("ACCOUNT_TOKEN_ACTIVE_KEY"),
      ).decrypt(user, subject, token),
  },
  async deleteUser(user) {
    const { error } = await admin.auth.admin.deleteUser(user, false);
    if (error) throw new Error("Account deletion failed");
  },
  now: () => Math.floor(Date.now() / 1000),
});
Deno.serve(handler);
