import assert from "node:assert/strict";
import { exportPKCS8, generateKeyPair, jwtVerify, SignJWT } from "jose";
import { appleClient } from "./apple.ts";
Deno.test("Apple transport signs short-lived client assertions and validates identity signature, issuer and audience", async () => {
  const signing = await generateKeyPair("ES256", { extractable: true }),
    apple = await generateKeyPair("RS256");
  const config = {
    clientId: "example.services",
    teamId: "TEAM-FIXTURE",
    keyId: "KEY-FIXTURE",
    privateKeyBase64: btoa(await exportPKCS8(signing.privateKey)),
  };
  let audience = config.clientId, status = 200, responseBody = "";
  const calls: string[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input), fields = init!.body as URLSearchParams;
    calls.push(url);
    assert.equal(init?.method, "POST");
    assert.equal(fields.get("client_id"), config.clientId);
    const { payload, protectedHeader } = await jwtVerify(
      fields.get("client_secret")!,
      signing.publicKey,
      {
        issuer: config.teamId,
        subject: config.clientId,
        audience: "https://appleid.apple.com",
      },
    );
    assert.equal(protectedHeader.kid, config.keyId);
    assert.ok(payload.exp! - payload.iat! <= 300);
    if (url.endsWith("/token")) {
      assert.equal(fields.get("grant_type"), "refresh_token");
      assert.equal(fields.get("refresh_token"), "refresh-fixture");
      const token = await new SignJWT({}).setProtectedHeader({ alg: "RS256" })
        .setIssuer("https://appleid.apple.com").setAudience(audience)
        .setSubject("apple-subject").setIssuedAt().setExpirationTime("5m").sign(
          apple.privateKey,
        );
      return Response.json({ id_token: token });
    }
    assert.equal(url, "https://appleid.apple.com/auth/revoke");
    assert.equal(fields.get("token"), "refresh-fixture");
    assert.equal(fields.get("token_type_hint"), "refresh_token");
    return new Response(responseBody, { status });
  };
  const client = appleClient(
    () => config,
    fetcher,
    () => Promise.resolve(apple.publicKey),
  );
  assert.equal(await client.validate("refresh-fixture"), "apple-subject");
  audience = "other-app";
  await assert.rejects(client.validate("refresh-fixture"));
  await client.revoke("refresh-fixture");
  status = 400;
  responseBody = "sensitive-upstream-body";
  await assert.rejects(
    client.revoke("refresh-fixture"),
    (error) => error instanceof Error && !error.message.includes(responseBody),
  );
  assert.ok(
    calls.every((url) => url.startsWith("https://appleid.apple.com/auth/")),
  );
  const wrongSignature = appleClient(
    () => config,
    fetcher,
    () => Promise.resolve(signing.publicKey),
  );
  await assert.rejects(wrongSignature.validate("refresh-fixture"));
});
