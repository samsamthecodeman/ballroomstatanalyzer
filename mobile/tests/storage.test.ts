import assert from "node:assert/strict";
import test from "node:test";
import { chunkStorage, withoutProviderTokens } from "../src/chunkStorage";
function setup() {
  const values = new Map<string, string>();
  let id = 0;
  const store = {
    getItemAsync: async (k: string) => values.get(k) ?? null,
    setItemAsync: async (k: string, v: string) => {
      values.set(k, v);
    },
    deleteItemAsync: async (k: string) => {
      values.delete(k);
    },
  };
  return {
    values,
    store,
    storage: chunkStorage(store, () => `revision-${++id}`),
  };
}
test("large Unicode session round-trips in small secure chunks and replaces old revisions", async () => {
  const { values, storage } = setup(),
    value = "💃".repeat(2400);
  await storage.setItem("session", value);
  assert.equal(await storage.getItem("session"), value);
  assert.ok(
    [...values.entries()]
      .filter(([key]) => key !== "session")
      .every(
        ([, chunk]) =>
          Array.from(chunk).length <= 400 &&
          Buffer.byteLength(chunk, "utf8") <= 1600,
      ),
  );
  await storage.setItem("session", "new-session");
  assert.equal(await storage.getItem("session"), "new-session");
  assert.equal(
    [...values.keys()].some((k) => k.includes("revision-1")),
    false,
  );
  await storage.removeItem("session");
  assert.equal(await storage.getItem("session"), null);
  assert.equal(values.size, 0);
});
test("failed write preserves the last complete session", async () => {
  const { store, storage } = setup();
  await storage.setItem("session", "previous");
  const write = store.setItemAsync;
  store.setItemAsync = async (key, value) => {
    if (key.includes("revision-2.1")) throw new Error("write failed");
    return write(key, value);
  };
  await assert.rejects(storage.setItem("session", "x".repeat(900)));
  assert.equal(await storage.getItem("session"), "previous");
});
test("concurrent refreshes serialize; missing chunks are not accepted as valid sessions", async () => {
  const { values, storage } = setup();
  await Promise.all([
    storage.setItem("session", "first"),
    storage.setItem("session", "second"),
  ]);
  assert.equal(await storage.getItem("session"), "second");
  values.delete("session.revision-2.0");
  assert.equal(await storage.getItem("session"), null);
});
test("corrupt metadata is ignored and provider tokens are excluded from persistence", async () => {
  const { values, storage } = setup();
  values.set("session", "invalid JSON");
  assert.equal(await storage.getItem("session"), null);
  const value = withoutProviderTokens(
    JSON.stringify({
      access_token: "app-token",
      refresh_token: "app-refresh",
      provider_token: "do-not-store",
      provider_refresh_token: "do-not-store",
    }),
  );
  assert.deepEqual(JSON.parse(value), {
    access_token: "app-token",
    refresh_token: "app-refresh",
  });
  assert.equal(withoutProviderTokens("pkce-verifier"), "pkce-verifier");
});
