export type AnalysisMode = "individual" | "couple";
export interface Dancer {
  id: number;
  name: string;
  location?: string;
}
export interface Couple {
  names: string[];
  label: string;
}
export interface EventResult {
  source: string;
  cid: number | string;
  eid: number | string;
  comp: string;
  date: string | null;
  event: string;
  style: string;
  level: string;
  category: string;
  partner: string;
  entry: string;
  place: number | null;
  entries: number | null;
  made_final: boolean;
  percentile: number | null;
  rounds_danced?: number | null;
  url: string;
}
export interface Analysis {
  name: string;
  display_name?: string;
  aid?: number;
  analysis_mode?: AnalysisMode;
  events: EventResult[];
  warnings: string[];
  status: string;
}
export interface BoardRow {
  rank: number;
  name: string;
  wins: number;
  events: number;
  competitions: number;
}
export interface Board {
  rows: BoardRow[];
  years: string[];
  unknown_venues: number;
  matching_names: number;
  total_names: number;
  mode: AnalysisMode;
  region: string;
  competitions: unknown[];
}
export interface SavedDancer {
  name: string;
  aid: number | null;
}
