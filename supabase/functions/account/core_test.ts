import assert from "node:assert/strict";
import {
  AccountError,
  accountHandler,
  type Actor,
  type Services,
  type VaultState,
} from "./core.ts";
import { tokenVault } from "./vault.ts";
const userA = "11111111-1111-1111-1111-111111111111",
  userB = "22222222-2222-2222-2222-222222222222";
function fixture(apple = false) {
  let now = 1000000,
    allowed = true,
    challenge: { hash: string; session: string; expires: number } | null = null,
    lease: string | null = null;
  let actor: Actor = {
    id: userA,
    sessionId: "session-a",
    oauthAt: now,
    hasApple: apple,
    appleSubjects: apple ? ["apple-a"] : [],
  };
  const events: string[] = [],
    calls: { user: string; action: string; data?: Record<string, unknown> }[] =
      [];
  let state: VaultState = {
    subject: null,
    token: null,
    revoked: false,
    session: null,
    authAt: null,
  };
  const services: Services = {
    async authenticate(token) {
      await Promise.resolve();
      if (token !== "valid") {
        throw new AccountError(401, "unauthorized", "Sign in.");
      }
      return actor;
    },
    async rpc(user, action, data = {}) {
      await Promise.resolve();
      calls.push({ user, action, data });
      if (action === "rate") return { allowed };
      if (action === "read") return { ...state };
      if (action === "save") {
        if (lease) return null;
        state = {
          subject: String(data.subject),
          token: data.token as VaultState["token"],
          revoked: false,
          session: String(data.session),
          authAt: Number(data.authAt),
        };
        challenge = null;
        return {};
      }
      if (action === "prepare") {
        if (lease) return null;
        challenge = {
          hash: String(data.hash),
          session: String(data.session),
          expires: now + 300,
        };
        return {};
      }
      if (action === "begin") {
        if (
          lease || !challenge || challenge.hash !== data.hash ||
          challenge.session !== data.session || challenge.expires <= now
        ) return null;
        challenge = null;
        lease = String(data.lease);
        return { ...state };
      }
      if (action === "revoked") {
        assert.equal(data.lease, lease);
        state.revoked = true;
        state.token = null;
        events.push("receipt");
        return {};
      }
      if (action === "release") {
        if (data.lease === lease) lease = null;
        return {};
      }
      throw new Error("Unexpected action");
    },
    apple: {
      async validate(token) {
        await Promise.resolve();
        assert.equal(token, "apple-refresh-fixture");
        events.push("validate");
        return "apple-a";
      },
      async revoke() {
        await Promise.resolve();
        events.push("revoke");
      },
    },
    vault: tokenVault({ test: btoa("k".repeat(32)) }, "test"),
    async deleteUser(user) {
      await Promise.resolve();
      assert.equal(user, actor.id);
      events.push("delete");
    },
    now: () => now,
  };
  const handle = accountHandler(services);
  async function send(body: unknown, token = "valid", method = "POST") {
    const response = await handle(
      new Request("https://example.test/account", {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
      }),
    );
    return { status: response.status, data: await response.json() };
  }
  return {
    services,
    send,
    events,
    calls,
    setActor: (a: Actor) => {
      actor = a;
    },
    getActor: () => actor,
    setNow: (value: number) => {
      now = value;
    },
    denyRate: () => {
      allowed = false;
    },
    getState: () => state,
  };
}
Deno.test("deletion requires POST, valid user, fresh OAuth, typed confirmation and a server challenge", async () => {
  const f = fixture();
  assert.equal((await f.send({}, "valid", "GET")).status, 405);
  assert.equal((await f.send({ action: "delete" }, "invalid")).status, 401);
  f.setActor({ ...f.getActor(), oauthAt: 1 });
  assert.equal((await f.send({ action: "prepare-delete" })).status, 401);
  assert.deepEqual(f.events, []);
});
Deno.test("caller identity is authoritative; confirmation is session-bound, expiring and single-use", async () => {
  const f = fixture(),
    prepared = await f.send({ action: "prepare-delete", userId: userB });
  assert.equal(prepared.data.userId, userA);
  assert.ok(f.calls.every((c) => c.user === userA));
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
    })).status,
    400,
  );
  f.setActor({ ...f.getActor(), sessionId: "other-session" });
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
      confirm: "DELETE",
    })).status,
    409,
  );
  f.setActor({ ...f.getActor(), sessionId: "session-a" });
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
      confirm: "DELETE",
      userId: userB,
    })).status,
    200,
  );
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
      confirm: "DELETE",
    })).status,
    409,
  );
  assert.deepEqual(f.events, ["delete"]);
  const expired = await f.send({ action: "prepare-delete" });
  f.setNow(1000300);
  f.setActor({ ...f.getActor(), oauthAt: 1000300 });
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: expired.data.confirmation,
      confirm: "DELETE",
    })).status,
    409,
  );
});
Deno.test("Apple token must match the authenticated identity and is encrypted without appearing in responses", async () => {
  const f = fixture(true);
  f.services.apple.validate = () => Promise.resolve("someone-else");
  const bad = await f.send({
    action: "save-apple-token",
    token: "apple-refresh-fixture",
  });
  assert.equal(bad.status, 403);
  assert.equal(f.calls.some((c) => c.action === "save"), false);
  f.services.apple.validate = () => Promise.resolve("apple-a");
  const good = await f.send({
    action: "save-apple-token",
    token: "apple-refresh-fixture",
  });
  assert.equal(good.status, 200);
  assert.equal(JSON.stringify(good).includes("apple-refresh-fixture"), false);
  const stored = f.getState();
  assert.ok(stored.token);
  assert.equal(JSON.stringify(stored).includes("apple-refresh-fixture"), false);
  assert.equal(
    await f.services.vault.decrypt(userA, "apple-a", stored.token!),
    "apple-refresh-fixture",
  );
});
Deno.test("Apple authorization is validated/revoked before credentials and account are removed", async () => {
  const f = fixture(true);
  assert.equal((await f.send({ action: "prepare-delete" })).status, 409);
  await f.send({ action: "save-apple-token", token: "apple-refresh-fixture" });
  f.events.length = 0;
  const prepared = await f.send({ action: "prepare-delete" });
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
      confirm: "DELETE",
    })).status,
    200,
  );
  assert.deepEqual(f.events, ["validate", "revoke", "receipt", "delete"]);
  assert.equal(f.getState().token, null);
});
Deno.test("Apple failure retains the account; failed account deletion can retry after a recorded revocation", async () => {
  const f = fixture(true);
  await f.send({ action: "save-apple-token", token: "apple-refresh-fixture" });
  let prepared = await f.send({ action: "prepare-delete" });
  f.services.apple.revoke = async () => {
    await Promise.resolve();
    throw new Error("private upstream detail");
  };
  const failed = await f.send({
    action: "delete",
    confirmation: prepared.data.confirmation,
    confirm: "DELETE",
  });
  assert.equal(failed.status, 503);
  assert.equal(f.events.includes("delete"), false);
  assert.equal(JSON.stringify(failed).includes("private upstream"), false);
  f.services.apple.revoke = async () => {
    await Promise.resolve();
    f.events.push("revoke");
  };
  f.services.deleteUser = async () => {
    await Promise.resolve();
    throw new Error("private database detail");
  };
  prepared = await f.send({ action: "prepare-delete" });
  await f.send({
    action: "delete",
    confirmation: prepared.data.confirmation,
    confirm: "DELETE",
  });
  assert.equal(f.getState().revoked, true);
  assert.equal(f.getState().token, null);
  const previousLogin = f.getActor();
  f.setActor({
    ...previousLogin,
    sessionId: "new-apple-login",
    oauthAt: previousLogin.oauthAt + 1,
  });
  assert.equal(
    (await f.send({ action: "prepare-delete" })).status,
    409,
    "An old revocation receipt must not authorize a new Apple grant",
  );
  f.setActor(previousLogin);
  f.events.length = 0;
  f.services.deleteUser = async () => {
    await Promise.resolve();
    f.events.push("delete");
  };
  prepared = await f.send({ action: "prepare-delete" });
  assert.equal(
    (await f.send({
      action: "delete",
      confirmation: prepared.data.confirmation,
      confirm: "DELETE",
    })).status,
    200,
  );
  assert.deepEqual(f.events, ["delete"]);
});
Deno.test("rate limits fail closed and malformed requests never delete accounts", async () => {
  const f = fixture();
  f.denyRate();
  assert.equal((await f.send({ action: "prepare-delete" })).status, 429);
  assert.deepEqual(f.events, []);
});
Deno.test("concurrent retries cannot revoke or delete the same account twice", async () => {
  const f = fixture(), prepared = await f.send({ action: "prepare-delete" });
  let unblock!: () => void, entered!: () => void;
  const gate = new Promise<void>((resolve) => {
    unblock = resolve;
  });
  const ready = new Promise<void>((resolve) => {
    entered = resolve;
  });
  f.services.deleteUser = async () => {
    entered();
    await gate;
    f.events.push("delete");
  };
  const input = {
    action: "delete",
    confirmation: prepared.data.confirmation,
    confirm: "DELETE",
  };
  const first = f.send(input);
  await ready;
  assert.equal((await f.send(input)).status, 409);
  unblock();
  assert.equal((await first).status, 200);
  assert.deepEqual(f.events, ["delete"]);
});
Deno.test("malformed and oversized bodies are rejected without calling account services", async () => {
  const f = fixture(), handler = accountHandler(f.services);
  for (
    const [body, status] of [["not-json", 400], [
      JSON.stringify({ action: "save-apple-token", token: "x".repeat(13000) }),
      413,
    ]] as const
  ) {
    const response = await handler(
      new Request("https://example.test/account", {
        method: "POST",
        headers: {
          Authorization: "Bearer valid",
          "Content-Type": "application/json",
        },
        body,
      }),
    );
    assert.equal(response.status, status);
  }
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.events, []);
});
