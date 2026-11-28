import assert from "node:assert/strict";
import test from "node:test";
import { deletionFlow, type DeletionOperations } from "../src/deletionFlow";
function setup() {
  const calls: string[] = [];
  const operations: DeletionOperations = {
    reauthenticate: async () => {
      calls.push("reauth");
      return "owner-a";
    },
    prepare: async () => {
      calls.push("prepare");
      return { userId: "owner-a", confirmation: "nonce", expiresIn: 300 };
    },
    currentUser: async () => "owner-a",
    remove: async () => {
      calls.push("remove");
      return { deleted: true };
    },
    signOut: async () => {
      calls.push("signout");
    },
  };
  return { operations, calls, flow: deletionFlow(operations) };
}
test("cancelled and wrong-account reauthentication cannot prepare deletion", async () => {
  const f = setup();
  f.operations.reauthenticate = async () => null;
  assert.equal(await f.flow.prepare("owner-a", "apple"), null);
  assert.deepEqual(f.calls, []);
  f.operations.reauthenticate = async () => "owner-b";
  await assert.rejects(
    f.flow.prepare("owner-a", "google"),
    /different account/,
  );
  assert.deepEqual(f.calls, []);
});
test("explicit DELETE, unchanged account, and positive server receipt are required before sign-out", async () => {
  const f = setup(),
    prepared = await f.flow.prepare("owner-a", "apple");
  assert.deepEqual(f.calls, ["reauth", "prepare"]);
  await assert.rejects(f.flow.finish(prepared!, "delete"), /Type DELETE/);
  f.operations.currentUser = async () => "owner-b";
  await assert.rejects(f.flow.finish(prepared!, "DELETE"), /account changed/);
  assert.equal(f.calls.includes("remove"), false);
  f.operations.currentUser = async () => "owner-a";
  await f.flow.finish(prepared!, "DELETE");
  assert.deepEqual(f.calls, ["reauth", "prepare", "remove", "signout"]);
});
test("failed or unconfirmed deletion retains the local session for retry", async () => {
  const f = setup(),
    prepared = await f.flow.prepare("owner-a", "google");
  f.operations.remove = async () => {
    throw new Error("Revocation failed");
  };
  await assert.rejects(f.flow.finish(prepared!, "DELETE"));
  f.operations.remove = async () => ({ deleted: false });
  await assert.rejects(f.flow.finish(prepared!, "DELETE"));
  assert.equal(f.calls.includes("signout"), false);
});
