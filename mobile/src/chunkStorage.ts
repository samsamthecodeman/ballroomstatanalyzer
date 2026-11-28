export interface KeyStore {
  getItemAsync(key: string): Promise<string | null>;
  setItemAsync(key: string, value: string): Promise<void>;
  deleteItemAsync(key: string): Promise<void>;
}
// Persist the app's Supabase session, never a Google/Apple provider token.
export function withoutProviderTokens(value: string) {
  try {
    const data = JSON.parse(value);
    if (data && typeof data === "object" && !Array.isArray(data)) {
      delete data.provider_token;
      delete data.provider_refresh_token;
      return JSON.stringify(data);
    }
  } catch {
    /* PKCE verifier storage is a plain string, not a session object. */
  }
  return value;
}
// Small chunks avoid Keychain item-size limits. Commit the pointer only after all chunks exist.
export function chunkStorage(store: KeyStore, randomId: () => string) {
  let queue: Promise<unknown> = Promise.resolve();
  const serial = <T>(run: () => Promise<T>): Promise<T> => {
    const next = queue.then(run, run);
    queue = next.catch(() => {});
    return next;
  };
  const metadata = async (
    key: string,
  ): Promise<{ id: string; count: number } | null> => {
    const raw = await store.getItemAsync(key);
    if (!raw) return null;
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      return null;
    }
    if (!data || typeof data !== "object") return null;
    return typeof data.id === "string" &&
      /^[\w-]+$/.test(data.id) &&
      Number.isInteger(data.count) &&
      data.count >= 0 &&
      data.count <= 128
      ? data
      : null;
  };
  const clean = async (
    key: string,
    data: { id: string; count: number } | null,
  ) => {
    if (data)
      await Promise.all(
        Array.from({ length: data.count }, (_, i) =>
          store.deleteItemAsync(`${key}.${data.id}.${i}`),
        ),
      );
  };
  return {
    getItem: (key: string) =>
      serial(async () => {
        const data = await metadata(key);
        if (!data) return null;
        const chunks = await Promise.all(
          Array.from({ length: data.count }, (_, i) =>
            store.getItemAsync(`${key}.${data.id}.${i}`),
          ),
        );
        return chunks.some((c) => c === null) ? null : chunks.join("");
      }),
    setItem: (key: string, value: string) =>
      serial(async () => {
        const previous = await metadata(key),
          points = Array.from(value),
          data = { id: randomId(), count: Math.ceil(points.length / 400) };
        if (data.count > 128)
          throw new Error("Session is too large to store securely.");
        try {
          for (let i = 0; i < data.count; i++)
            await store.setItemAsync(
              `${key}.${data.id}.${i}`,
              points.slice(i * 400, (i + 1) * 400).join(""),
            );
          await store.setItemAsync(key, JSON.stringify(data));
        } catch (error) {
          await clean(key, data).catch(() => {});
          throw error;
        }
        await clean(key, previous).catch(() => {});
      }),
    removeItem: (key: string) =>
      serial(async () => {
        const data = await metadata(key);
        await store.deleteItemAsync(key);
        await clean(key, data);
      }),
  };
}
