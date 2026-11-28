import { supabase } from "./client";
export type { DeletionConfirmation } from "./deletionFlow";
export class AccountActionError extends Error {
  constructor(
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}
export async function accountAction<T>(
  body: Record<string, unknown>,
): Promise<T> {
  if (!supabase) throw new Error("Sign in first.");
  const { data, error } = await supabase.functions.invoke("account", { body });
  if (error) {
    let details: { error?: string; code?: string } = {};
    if ("context" in error && error.context instanceof Response) {
      try {
        details = await error.context.json();
      } catch {
        /* Do not expose raw gateway responses. */
      }
    }
    throw new AccountActionError(
      details.error || "Account management could not finish. Please try again.",
      details.code,
    );
  }
  if (data?.error) throw new AccountActionError(data.error, data.code);
  return data as T;
}
