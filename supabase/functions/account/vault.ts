export interface Envelope {
  v: 1;
  kid: string;
  iv: string;
  data: string;
}
const encode = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));
const decode = (value: string) =>
  Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
export function tokenVault(keyring: Record<string, string>, active: string) {
  async function key(id: string) {
    if (!Object.hasOwn(keyring, id)) throw new Error("Unknown encryption key");
    const raw = decode(keyring[id]);
    if (raw.length !== 32) throw new Error("Expected a 256-bit encryption key");
    return await crypto.subtle.importKey("raw", raw, "AES-GCM", false, [
      "encrypt",
      "decrypt",
    ]);
  }
  const aad = (user: string, subject: string) =>
    new TextEncoder().encode(JSON.stringify(["apple", 1, user, subject]));
  return {
    async encrypt(
      user: string,
      subject: string,
      token: string,
    ): Promise<Envelope> {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const bytes = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv, additionalData: aad(user, subject) },
        await key(active),
        new TextEncoder().encode(token),
      );
      return {
        v: 1,
        kid: active,
        iv: encode(iv),
        data: encode(new Uint8Array(bytes)),
      };
    },
    async decrypt(user: string, subject: string, envelope: Envelope) {
      if (envelope.v !== 1 || typeof envelope.kid !== "string") {
        throw new Error("Invalid token envelope");
      }
      const iv = decode(envelope.iv), bytes = decode(envelope.data);
      if (iv.length !== 12 || bytes.length < 17 || bytes.length > 20000) {
        throw new Error("Invalid encrypted token");
      }
      const plain = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv, additionalData: aad(user, subject) },
        await key(envelope.kid),
        bytes,
      );
      return new TextDecoder().decode(plain);
    },
  };
}
