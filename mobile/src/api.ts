import * as Crypto from "expo-crypto";
import { Platform } from "react-native";
import { storage } from "./client";
import type { Analysis, Board, Couple, Dancer } from "./types";
import { analysisParams } from "./results";

export const API_URL = (
  process.env.EXPO_PUBLIC_API_URL || "https://bsa.sam-moran.com"
).replace(/\/$/, "");
if (!API_URL.startsWith("https://"))
  throw new Error("The mobile API must use HTTPS.");
let visitor: Promise<string> | undefined;
function visitorId() {
  return (visitor ??= (async () => {
    let value = await storage.getItem("bsa-visitor");
    if (!value) {
      value = Crypto.randomUUID().replaceAll("-", "");
      await storage.setItem("bsa-visitor", value);
    }
    return value;
  })());
}
async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController(),
    abort = () => controller.abort();
  signal?.addEventListener("abort", abort);
  if (signal?.aborted) abort();
  const timeout = setTimeout(abort, 20000);
  try {
    const base =
      Platform.OS === "web" && process.env.EXPO_PUBLIC_PREVIEW_PROXY === "1"
        ? ""
        : API_URL;
    const response = await fetch(base + path, {
      signal: controller.signal,
      method: body === undefined ? "GET" : "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Visitor": await visitorId(),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(
        "The website is temporarily unavailable. Please try again.",
      );
    }
    if (!response.ok)
      throw new Error(data.error || `The request failed (${response.status}).`);
    return data;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
export const dancers = (query: string, signal?: AbortSignal) =>
  request<{ dancers: Dancer[] }>(
    "/api/dancers?q=" + encodeURIComponent(query),
    undefined,
    signal,
  );
export const couples = (query: string, signal?: AbortSignal) =>
  request<{ couples: Couple[] }>(
    "/api/couples?q=" + encodeURIComponent(query),
    undefined,
    signal,
  );
export const leaderboard = (
  filters: Record<string, string>,
  signal?: AbortSignal,
) =>
  request<Board>(
    "/api/texas?" + new URLSearchParams(filters),
    undefined,
    signal,
  );
export async function analyze(
  params: ReturnType<typeof analysisParams>,
  progress: (message: string) => void,
  signal: AbortSignal,
) {
  // Retain the job ID even if Stop is tapped while the start request is in flight.
  const { id } = await request<{ id: string }>("/api/start", params);
  let done = false;
  try {
    while (!signal.aborted) {
      const job = await request<{
        state: string;
        message: string;
        error?: string;
        result: Analysis;
      }>("/api/status?id=" + id, undefined, signal);
      if (job.state === "done") {
        done = true;
        return job.result;
      }
      if (job.state === "error" || job.state === "cancelled")
        throw new Error(job.error || "Search stopped.");
      progress(job.message || "Looking up results…");
      await new Promise<void>((resolve) => {
        const stop = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", stop);
          resolve();
        };
        const timer = setTimeout(stop, 800);
        signal.addEventListener("abort", stop, { once: true });
        if (signal.aborted) stop();
      });
    }
    throw new Error("Search stopped.");
  } finally {
    if (!done) await request("/api/cancel", { id }).catch(() => {});
  }
}
