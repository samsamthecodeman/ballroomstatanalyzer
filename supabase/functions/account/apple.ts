import {
  createRemoteJWKSet,
  importPKCS8,
  jwtVerify,
  type JWTVerifyGetKey,
  SignJWT,
} from "jose";
import { AccountError } from "./core.ts";
interface AppleConfig {
  clientId: string;
  teamId: string;
  keyId: string;
  privateKeyBase64: string;
}
export function appleClient(
  config: () => AppleConfig,
  fetcher = fetch,
  keys: JWTVerifyGetKey = createRemoteJWKSet(
    new URL("https://appleid.apple.com/auth/keys"),
    { timeoutDuration: 10000 },
  ),
) {
  async function credentials() {
    const c = config();
    if (!c.clientId || !c.teamId || !c.keyId || !c.privateKeyBase64) {
      throw new Error("Apple server configuration is incomplete");
    }
    const key = await importPKCS8(atob(c.privateKeyBase64), "ES256");
    const secret = await new SignJWT({}).setProtectedHeader({
      alg: "ES256",
      kid: c.keyId,
    })
      .setIssuer(c.teamId).setSubject(c.clientId).setAudience(
        "https://appleid.apple.com",
      )
      .setIssuedAt().setExpirationTime("5m").sign(key);
    return { ...c, secret };
  }
  return {
    async validate(token: string) {
      const c = await credentials();
      const response = await fetcher("https://appleid.apple.com/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        signal: AbortSignal.timeout(10000),
        body: new URLSearchParams({
          client_id: c.clientId,
          client_secret: c.secret,
          grant_type: "refresh_token",
          refresh_token: token,
        }),
      });
      if (!response.ok) {
        throw new AccountError(
          409,
          "apple_reauth_required",
          "Sign in with Apple again to refresh authorization.",
        );
      }
      const data = await response.json();
      if (typeof data.id_token !== "string") {
        throw new Error("Apple did not provide an identity token");
      }
      const { payload } = await jwtVerify(data.id_token, keys, {
        issuer: "https://appleid.apple.com",
        audience: c.clientId,
        algorithms: ["RS256"],
      });
      if (!payload.sub) throw new Error("Apple identity is missing");
      return payload.sub;
    },
    async revoke(token: string) {
      const c = await credentials();
      const response = await fetcher("https://appleid.apple.com/auth/revoke", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        signal: AbortSignal.timeout(10000),
        body: new URLSearchParams({
          client_id: c.clientId,
          client_secret: c.secret,
          token,
          token_type_hint: "refresh_token",
        }),
      });
      if (response.status !== 200) {
        throw new AccountError(
          503,
          "apple_revocation_failed",
          "Apple authorization could not be revoked. Your account was retained; please retry.",
        );
      }
    },
  };
}
