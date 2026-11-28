import type { Analysis, EventResult } from "./types";

export const STYLES = [
  "International Standard",
  "International Latin",
  "American Smooth",
  "American Rhythm",
  "Social",
  "Country",
  "Cabaret / Show",
  "Other",
];
export const CATEGORIES = [
  "Couple-judged",
  "Solo proficiency leads",
  "Solo proficiency follows",
  "Solo",
];
export function analysisParams(
  query: string,
  partner: string,
  mode: "individual" | "couple",
  aid?: number,
) {
  const value = query.trim();
  if (!value) throw new Error("Enter a dancer name or ID.");
  if (mode === "couple" && !partner.trim())
    throw new Error("Enter a second dancer or choose a couple.");
  if (
    mode === "couple" &&
    value.toLocaleLowerCase() === partner.trim().toLocaleLowerCase()
  )
    throw new Error("Choose two different dancers.");
  return {
    name: /^\d+$/.test(value) ? "" : value,
    aid: /^\d+$/.test(value) ? Number(value) : aid,
    partner: mode === "couple" ? partner.trim() : "",
    analysis_mode: mode,
  };
}
export function filterEvents(
  events: EventResult[],
  styles: string[],
  competition: string,
  category: string,
  uncontested: boolean,
) {
  return events.filter(
    (e) =>
      (!styles.length || styles.includes(e.style)) &&
      (!competition || String(e.cid) === competition) &&
      (!category || category === e.category) &&
      (!uncontested || e.entries !== 1),
  );
}
export function summarize(events: EventResult[]) {
  const scored = events.filter((e) => typeof e.percentile === "number");
  return {
    events: events.length,
    wins: events.filter((e) => e.place === 1).length,
    podiums: events.filter((e) => e.place !== null && e.place <= 3).length,
    finals: events.filter((e) => e.made_final).length,
    field: scored.length
      ? Math.round(
          scored.reduce((sum, e) => sum + e.percentile!, 0) / scored.length,
        )
      : null,
  };
}
export function resultError(data: Analysis) {
  if (data.status === "ok") return null;
  return data.analysis_mode === "couple"
    ? "No shared results matched this couple. Check both published names."
    : "No results matched this dancer. Choose a name suggestion or check the dancer ID.";
}
export function callbackCode(url: string) {
  const parsed = new URL(url);
  if (
    parsed.protocol !== "com.sammoran.ballroomstats:" ||
    parsed.hostname !== "auth" ||
    parsed.pathname !== "/callback"
  )
    return null;
  const error =
    parsed.searchParams.get("error_description") ||
    parsed.searchParams.get("error");
  if (error) throw new Error(error);
  return parsed.searchParams.get("code");
}
