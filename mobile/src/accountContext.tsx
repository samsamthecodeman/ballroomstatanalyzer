import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Session } from "@supabase/supabase-js";
import { authConfigured, supabase } from "./client";
import {
  getSavedDancer,
  listenForAuth,
  prepareAccountDeletion,
  saveDancer,
} from "./auth";
import type { DeletionConfirmation } from "./deletionFlow";
import type { SavedDancer } from "./types";
import { errorMessage } from "./AnalysisScreen";
interface Account {
  session: Session | null;
  saved: SavedDancer | null;
  ready: boolean;
  error: string;
  dismissError: () => void;
  save: (dancer: SavedDancer) => Promise<void>;
  analysisKey: number;
  reloadAnalysis: () => void;
  deletionConfirmation: DeletionConfirmation | null;
  preparingDeletion: boolean;
  prepareDeletion: () => Promise<void>;
  cancelDeletion: () => void;
}
const Context = createContext<Account | null>(null);
export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null),
    [ready, setReady] = useState(!authConfigured);
  const [profile, setProfile] = useState<{
      owner: string;
      dancer: SavedDancer | null;
    } | null>(null),
    [error, setError] = useState(""),
    [analysisKey, setAnalysisKey] = useState(0);
  const userId = useRef<string | undefined>(undefined),
    ownerId = session?.user.id;
  const saved = profile?.owner === ownerId ? (profile?.dancer ?? null) : null;
  const [deletionConfirmation, setDeletionConfirmation] =
      useState<DeletionConfirmation | null>(null),
    [preparingDeletion, setPreparingDeletion] = useState(false);
  useEffect(() => {
    if (!supabase) return;
    let active = true;
    supabase.auth
      .getSession()
      .then(({ data, error }) => {
        if (active) {
          userId.current = data.session?.user.id;
          setSession(data.session);
          setReady(true);
          if (error) setError(errorMessage(error));
        }
      })
      .catch((err) => {
        if (active) {
          setReady(true);
          setError(errorMessage(err));
        }
      });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      userId.current = next?.user.id;
      setSession(next);
      if (!next) {
        setProfile(null);
        setDeletionConfirmation(null);
      }
      setReady(true);
    });
    const dispose = listenForAuth((err) => setError(errorMessage(err)));
    return () => {
      active = false;
      data.subscription.unsubscribe();
      dispose();
    };
  }, []);
  useEffect(() => {
    let active = true;
    if (ownerId)
      getSavedDancer(ownerId)
        .then((d) => {
          if (active) setProfile({ owner: ownerId, dancer: d });
        })
        .catch((err) => {
          if (active) setError(errorMessage(err));
        });
    return () => {
      active = false;
    };
  }, [ownerId]);
  async function save(dancer: SavedDancer) {
    if (!session) return;
    const owner = session.user.id;
    await saveDancer(owner, dancer);
    if (userId.current === owner) setProfile({ owner, dancer });
  }
  async function prepareDeletion() {
    if (!session) return;
    const owner = session.user.id;
    const provider =
      session.user.identities?.some((i) => i.provider === "apple") ||
      session.user.app_metadata.providers?.includes("apple")
        ? "apple"
        : "google";
    setPreparingDeletion(true);
    setDeletionConfirmation(null);
    setError("");
    try {
      const prepared = await prepareAccountDeletion(owner, provider);
      if (userId.current === owner) setDeletionConfirmation(prepared);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPreparingDeletion(false);
    }
  }
  return (
    <Context.Provider
      value={{
        session,
        saved,
        ready,
        error,
        dismissError: () => setError(""),
        save,
        analysisKey,
        reloadAnalysis: () => setAnalysisKey((value) => value + 1),
        deletionConfirmation,
        preparingDeletion,
        prepareDeletion,
        cancelDeletion: () => setDeletionConfirmation(null),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useAccount() {
  const account = useContext(Context);
  if (!account) throw new Error("Missing account provider");
  return account;
}
