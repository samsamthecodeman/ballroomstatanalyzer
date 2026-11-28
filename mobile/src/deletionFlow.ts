export interface DeletionConfirmation {
  confirmation: string;
  userId: string;
  expiresIn: number;
}
export interface DeletionOperations {
  reauthenticate: (
    provider: "google" | "apple",
  ) => Promise<string | null | undefined>;
  prepare: () => Promise<DeletionConfirmation>;
  currentUser: () => Promise<string | null>;
  remove: (confirmation: string) => Promise<{ deleted: boolean }>;
  signOut: () => Promise<void>;
}
export function deletionFlow(operations: DeletionOperations) {
  return {
    async prepare(
      userId: string,
      provider: "google" | "apple",
    ): Promise<DeletionConfirmation | null> {
      const signedIn = await operations.reauthenticate(provider);
      if (!signedIn) return null;
      if (signedIn !== userId)
        throw new Error(
          "You signed in to a different account. No deletion was requested.",
        );
      const prepared = await operations.prepare();
      if (prepared.userId !== userId)
        throw new Error("The account changed. Restart deletion confirmation.");
      return prepared;
    },
    async finish(prepared: DeletionConfirmation, typed: string) {
      if (typed !== "DELETE") throw new Error("Type DELETE to confirm.");
      if ((await operations.currentUser()) !== prepared.userId)
        throw new Error("The account changed. Restart deletion confirmation.");
      const result = await operations.remove(prepared.confirmation);
      if (result.deleted !== true)
        throw new Error("Account deletion could not be confirmed.");
      await operations.signOut();
    },
  };
}
