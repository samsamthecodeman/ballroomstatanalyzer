import type { Envelope } from "./vault.ts";
export class AccountError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}
export interface Actor {
  id: string;
  sessionId: string;
  oauthAt: number;
  hasApple: boolean;
  appleSubjects: string[];
}
export interface VaultState {
  subject: string | null;
  token: Envelope | null;
  revoked: boolean;
  session: string | null;
  authAt: number | null;
}
export interface Services {
  authenticate: (bearer: string) => Promise<Actor>;
  rpc: (
    user: string,
    action: string,
    data?: Record<string, unknown>,
  ) => Promise<unknown>;
  apple: {
    validate: (token: string) => Promise<string>;
    revoke: (token: string) => Promise<void>;
  };
  vault: {
    encrypt: (
      user: string,
      subject: string,
      token: string,
    ) => Promise<Envelope>;
    decrypt: (
      user: string,
      subject: string,
      token: Envelope,
    ) => Promise<string>;
  };
  deleteUser: (user: string) => Promise<void>;
  now: () => number;
}
function fail(status: number, code: string, message: string): never {
  throw new AccountError(status, code, message);
}
const digest = async (text: string) =>
  Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
function recent(actor: Actor, now: number) {
  if (
    !actor.sessionId || !Number.isFinite(actor.oauthAt) ||
    actor.oauthAt < now - 300 || actor.oauthAt > now + 30
  ) {
    fail(401, "reauth_required", "Sign in again before managing this account.");
  }
  if (actor.hasApple && actor.appleSubjects.length !== 1) {
    fail(
      409,
      "apple_identity_required",
      "The Apple identity could not be verified. Account deletion is unavailable.",
    );
  }
}
function checkApple(actor: Actor, state: VaultState) {
  if (
    actor.hasApple &&
    (!state || !state.subject || !actor.appleSubjects.includes(state.subject) ||
      (!state.token && !state.revoked) || state.session !== actor.sessionId ||
      state.authAt !== actor.oauthAt)
  ) {
    fail(
      409,
      "apple_reauth_required",
      "Sign in with Apple again to prepare account deletion.",
    );
  }
  if (state?.subject && !state.token && !state.revoked) {
    fail(
      409,
      "apple_reauth_required",
      "Apple authorization is unavailable. Sign in with Apple again.",
    );
  }
}
async function body(request: Request): Promise<Record<string, unknown>> {
  if (
    !(request.headers.get("content-type") || "").startsWith("application/json")
  ) fail(415, "invalid_body", "Send JSON.");
  const reader = request.body?.getReader();
  let size = 0;
  const chunks: Uint8Array[] = [];
  if (!reader) fail(400, "invalid_body", "Missing request body.");
  while (true) {
    const next = await reader.read();
    if (next.done) break;
    size += next.value.length;
    if (size > 12000) {
      await reader.cancel();
      fail(413, "invalid_body", "Request is too large.");
    }
    chunks.push(next.value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    fail(400, "invalid_body", "Invalid JSON.");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(400, "invalid_body", "Invalid JSON object.");
  }
  return value;
}
export function accountHandler(services: Services) {
  return async (request: Request): Promise<Response> => {
    const reply = (data: unknown, status = 200) =>
      Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
    try {
      if (request.method !== "POST") {
        return reply({ error: "Use POST.", code: "method_not_allowed" }, 405);
      }
      const authorization = request.headers.get("authorization") || "";
      if (!/^Bearer [^\s]{1,10000}$/.test(authorization)) {
        fail(401, "unauthorized", "Sign in first.");
      }
      const actor = await services.authenticate(authorization.slice(7));
      const input = await body(request);
      if (
        !["save-apple-token", "prepare-delete", "delete"].includes(
          String(input.action),
        )
      ) fail(400, "invalid_action", "Unknown account action.");
      const rate = await services.rpc(actor.id, "rate") as { allowed: boolean };
      if (!rate.allowed) {
        fail(429, "rate_limited", "Please wait a minute before trying again.");
      }
      recent(actor, services.now());
      if (input.action === "save-apple-token") {
        if (
          !actor.hasApple || typeof input.token !== "string" ||
          !input.token.length || input.token.length > 8000
        ) {
          fail(400, "invalid_apple_token", "Missing Apple authorization.");
        }
        const subject = await services.apple.validate(input.token);
        if (!actor.appleSubjects.includes(subject)) {
          fail(
            403,
            "apple_identity_mismatch",
            "Apple authorization does not match this account.",
          );
        }
        const encrypted = await services.vault.encrypt(
          actor.id,
          subject,
          input.token,
        );
        const saved = await services.rpc(actor.id, "save", {
          subject,
          token: encrypted,
          session: actor.sessionId,
          authAt: actor.oauthAt,
        });
        if (saved === null) {
          fail(
            409,
            "deletion_busy",
            "An account-deletion request is already running.",
          );
        }
        return reply({ saved: true });
      }
      if (input.action === "prepare-delete") {
        const state = await services.rpc(actor.id, "read") as VaultState;
        checkApple(actor, state);
        const confirmation = crypto.randomUUID() + crypto.randomUUID();
        const prepared = await services.rpc(actor.id, "prepare", {
          hash: await digest(confirmation),
          session: actor.sessionId,
        });
        if (prepared === null) {
          fail(
            409,
            "deletion_busy",
            "An account-deletion request is already running.",
          );
        }
        return reply({ confirmation, userId: actor.id, expiresIn: 300 });
      }
      if (
        input.confirm !== "DELETE" || typeof input.confirmation !== "string" ||
        !/^[a-f0-9-]{72}$/.test(input.confirmation)
      ) {
        fail(
          400,
          "confirmation_required",
          "Explicit deletion confirmation is required.",
        );
      }
      const lease = crypto.randomUUID();
      const state = await services.rpc(actor.id, "begin", {
        hash: await digest(input.confirmation),
        session: actor.sessionId,
        lease,
      }) as VaultState | null;
      if (!state) {
        fail(
          409,
          "confirmation_expired",
          "Restart deletion confirmation. It expired or was already used.",
        );
      }
      try {
        checkApple(actor, state);
        if ((actor.hasApple || state.subject) && !state.revoked) {
          const token = await services.vault.decrypt(
            actor.id,
            state.subject!,
            state.token!,
          );
          if (await services.apple.validate(token) !== state.subject) {
            fail(
              403,
              "apple_identity_mismatch",
              "Apple authorization does not match this account.",
            );
          }
          await services.apple.revoke(token);
          const marked = await services.rpc(actor.id, "revoked", { lease });
          if (marked === null) {
            fail(
              409,
              "deletion_busy",
              "Account deletion could not finish. Please retry.",
            );
          }
        }
        await services.deleteUser(actor.id);
        return reply({ deleted: true });
      } finally {
        // The row may already be gone through auth.users ON DELETE CASCADE.
        await services.rpc(actor.id, "release", { lease }).catch(() => {});
      }
    } catch (error) {
      if (error instanceof AccountError) {
        return reply({ error: error.message, code: error.code }, error.status);
      }
      // Never log or return provider responses, credentials, request bodies, or raw SDK errors.
      return reply({
        error: "Account management could not finish. Please try again.",
        code: "account_unavailable",
      }, 503);
    }
  };
}
