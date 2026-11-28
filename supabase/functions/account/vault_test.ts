import assert from "node:assert/strict";
import { tokenVault } from "./vault.ts";
Deno.test("AES-GCM binds tokens to owner, Apple subject and key ID; ciphertext is randomized", async () => {
  const vault = tokenVault({ old: btoa("a".repeat(32)) }, "old");
  const first = await vault.encrypt("owner-a", "apple-a", "sensitive-fixture");
  const second = await vault.encrypt("owner-a", "apple-a", "sensitive-fixture");
  assert.notEqual(first.iv, second.iv);
  assert.notEqual(first.data, second.data);
  assert.equal(
    await vault.decrypt("owner-a", "apple-a", first),
    "sensitive-fixture",
  );
  await assert.rejects(vault.decrypt("owner-b", "apple-a", first));
  await assert.rejects(vault.decrypt("owner-a", "apple-b", first));
  await assert.rejects(
    vault.decrypt("owner-a", "apple-a", {
      ...first,
      data: first.data.slice(0, -4) + "AAAA",
    }),
  );
  const rotated = tokenVault({
    old: btoa("a".repeat(32)),
    next: btoa("b".repeat(32)),
  }, "next");
  assert.equal(
    await rotated.decrypt("owner-a", "apple-a", first),
    "sensitive-fixture",
  );
  assert.equal(
    (await rotated.encrypt("owner-a", "apple-a", "value")).kid,
    "next",
  );
  await assert.rejects(
    tokenVault({ next: btoa("b".repeat(32)) }, "next").decrypt(
      "owner-a",
      "apple-a",
      first,
    ),
  );
  await assert.rejects(
    tokenVault({ bad: "short" }, "bad").encrypt("owner", "subject", "value"),
  );
});
