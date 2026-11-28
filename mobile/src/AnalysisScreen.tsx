import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { analyze, couples, dancers } from "./api";
import {
  analysisParams,
  CATEGORIES,
  filterEvents,
  resultError,
  summarize,
} from "./results";
import type {
  Analysis,
  AnalysisMode,
  Couple,
  Dancer,
  SavedDancer,
} from "./types";
import { Button, Choice, Heading, Input, Note, s, usePalette } from "./ui";
export const errorMessage = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong. Please try again.";
export const toggle = (values: string[], value: string) =>
  values.includes(value)
    ? values.filter((v) => v !== value)
    : [...values, value];

export default function AnalysisScreen({
  saved,
  signedIn,
  onSave,
}: {
  saved: SavedDancer | null;
  signedIn: boolean;
  onSave: (d: SavedDancer) => Promise<void>;
}) {
  const c = usePalette(),
    controller = useRef<AbortController | null>(null);
  const [mode, setMode] = useState<AnalysisMode>("individual"),
    [query, setQuery] = useState(saved?.name || ""),
    [partner, setPartner] = useState("");
  const [picked, setPicked] = useState<Dancer | null>(
      saved?.aid ? { name: saved.name, id: saved.aid } : null,
    ),
    [pickedName, setPickedName] = useState(saved?.name || ""),
    [matches, setMatches] = useState<(Dancer | Couple)[]>([]);
  const [data, setData] = useState<Analysis | null>(null),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(""),
    [error, setError] = useState("");
  const [styles, setStyles] = useState<string[]>([]),
    [competition, setCompetition] = useState(""),
    [category, setCategory] = useState(""),
    [uncontested, setUncontested] = useState(false);
  const [sort, setSort] = useState("date"),
    [descending, setDescending] = useState(true),
    [limit, setLimit] = useState(50);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (
      busy ||
      query.trim().length < 3 ||
      /^\d+$/.test(query.trim()) ||
      query === pickedName
    )
      return;
    const abort = new AbortController(),
      timer = setTimeout(async () => {
        try {
          const result =
            mode === "couple"
              ? (await couples(query.trim(), abort.signal)).couples
              : (await dancers(query.trim(), abort.signal)).dancers;
          if (!abort.signal.aborted) setMatches(result);
        } catch (err) {
          if (!abort.signal.aborted) setStatus(errorMessage(err));
        }
      }, 500);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [query, mode, busy, pickedName]);
  function choose(match: Dancer | Couple) {
    if ("names" in match) {
      setQuery(match.names[0]);
      setPartner(match.names[1]);
      setPickedName(match.names[0]);
      setPicked(null);
    } else {
      setQuery(match.name);
      setPicked(match);
      setPickedName(match.name);
    }
    setMatches([]);
  }
  async function run() {
    let params;
    try {
      params = analysisParams(
        query,
        partner,
        mode,
        picked?.name === query ? picked.id : undefined,
      );
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setError("");
    setBusy(true);
    setStatus("Looking up saved results…");
    try {
      const result = await analyze(params, setStatus, abort.signal);
      if (abort.signal.aborted) return;
      const problem = resultError(result);
      if (problem) throw new Error(problem);
      setData(result);
      setStyles([]);
      setCompetition("");
      setCategory("");
      setUncontested(false);
      setLimit(50);
      setStatus("");
    } catch (err) {
      if (!abort.signal.aborted) setError(errorMessage(err));
    } finally {
      if (controller.current === abort) setBusy(false);
    }
  }
  const filtered = useMemo(
    () =>
      filterEvents(
        data?.events || [],
        styles,
        competition,
        category,
        uncontested,
      ),
    [data, styles, competition, category, uncontested],
  );
  const rows = useMemo(
    () =>
      [...filtered].sort((a, b) => {
        const value = (r: typeof a) =>
          sort === "rounds"
            ? r.rounds_danced
            : sort === "field"
              ? r.entries
              : sort === "final"
                ? Number(r.made_final)
                : sort === "event"
                  ? r.event
                  : sort === "partner"
                    ? r.partner || "(solo)"
                    : sort === "place"
                      ? r.place
                      : r.date;
        const av = value(a),
          bv = value(b);
        if (av == null) return bv == null ? 0 : 1;
        if (bv == null) return -1;
        return (
          (typeof av === "string"
            ? av.localeCompare(String(bv), undefined, { numeric: true })
            : Number(av) - Number(bv)) * (descending ? -1 : 1)
        );
      }),
    [filtered, sort, descending],
  );
  const stats = summarize(filtered),
    comps = [
      ...new Map(
        (data?.events || []).map((e) => [String(e.cid), e.comp]),
      ).entries(),
    ];
  return (
    <ScrollView
      contentContainerStyle={s.screen}
      keyboardShouldPersistTaps="handled"
    >
      <Heading
        title={"Every heat.\nEvery final."}
        subtitle="Your competition story, together. BCE + O2CM."
      />
      <View style={s.row}>
        {(["individual", "couple"] as const).map((v) => (
          <Button
            key={v}
            title={v === "individual" ? "Individual" : "Couple"}
            quiet={mode !== v}
            disabled={busy}
            onPress={() => {
              setMode(v);
              setMatches([]);
              setPickedName("");
              setPicked(null);
            }}
          />
        ))}
      </View>
      <View style={{ height: 16 }} />
      <Input
        accessibilityLabel="Dancer name or ID"
        placeholder={
          mode === "couple"
            ? "Type 3+ letters to find a couple"
            : "Name or dancer ID"
        }
        value={query}
        editable={!busy}
        onChangeText={(v) => {
          setQuery(v);
          setMatches([]);
          setPicked(null);
          setPickedName("");
        }}
      />
      {mode === "couple" && (
        <Input
          accessibilityLabel="Second dancer name"
          placeholder="Second dancer’s full name"
          value={partner}
          editable={!busy}
          onChangeText={setPartner}
        />
      )}
      {matches.slice(0, 8).map((match, index) => (
        <Pressable
          key={index}
          accessibilityRole="button"
          onPress={() => choose(match)}
          style={[s.card, { borderColor: c.line }]}
        >
          <Text style={{ color: c.ink }}>
            {"label" in match ? match.label : `${match.name} · ID ${match.id}`}
          </Text>
        </Pressable>
      ))}
      <View style={s.row}>
        <Button
          title={busy ? "Analyzing…" : "Analyze"}
          disabled={busy}
          onPress={run}
        />
        {busy && (
          <Button
            title="Stop"
            quiet
            onPress={() => {
              controller.current?.abort();
              setBusy(false);
              setStatus("Search stopped.");
            }}
          />
        )}
      </View>
      {busy && <ActivityIndicator style={{ marginTop: 12 }} color={c.ink} />}
      {status ? <Note>{status}</Note> : null}
      {error ? <Note error>{error}</Note> : null}
      {data && (
        <>
          <Text
            accessibilityRole="header"
            style={[s.section, { color: c.ink }]}
          >
            {data.display_name || data.name}
          </Text>
          {signedIn && (
            <Button
              title="Save first dancer to my account"
              quiet
              onPress={() =>
                onSave({ name: data.name, aid: data.aid || null })
                  .then(() => setStatus("Dancer saved to your account."))
                  .catch((err) => setError(errorMessage(err)))
              }
            />
          )}
          <View style={s.row}>
            {[
              ["Events", stats.events],
              ["Wins", stats.wins],
              ["Top 3", stats.podiums],
              ["Finals", stats.finals],
              ["Field beaten", stats.field === null ? "—" : `${stats.field}%`],
            ].map(([label, value]) => (
              <View key={label} style={s.metric}>
                <Text
                  style={{
                    color: label === "Events" ? c.ink : c.green,
                    fontSize: 34,
                    fontWeight: "600",
                  }}
                >
                  {value}
                </Text>
                <Text style={{ color: c.muted }}>{label}</Text>
              </View>
            ))}
          </View>
          <Note>
            Field beaten measures placement from 100% for first to 0% for last.
            Events are weighted equally.
          </Note>
          <Text style={[s.section, { color: c.ink }]}>Filters</Text>
          <Note>
            Choose multiple styles. None selected includes all styles.
          </Note>
          <View style={s.row}>
            {[...new Set(data.events.map((e) => e.style))].sort().map((v) => (
              <Choice
                key={v}
                title={v}
                checked={styles.includes(v)}
                onPress={() => {
                  setStyles(toggle(styles, v));
                  setLimit(50);
                }}
              />
            ))}
          </View>
          <Text style={[s.note, { color: c.ink }]}>Competition</Text>
          <ScrollView horizontal contentContainerStyle={s.row}>
            <Choice
              title="All competitions"
              checked={!competition}
              onPress={() => setCompetition("")}
            />
            {comps.map(([id, title]) => (
              <Choice
                key={id}
                title={title}
                checked={competition === id}
                onPress={() => {
                  setCompetition(id);
                  setLimit(50);
                }}
              />
            ))}
          </ScrollView>
          <Text style={[s.note, { color: c.ink }]}>Judging category</Text>
          <View style={s.row}>
            <Choice
              title="All categories"
              checked={!category}
              onPress={() => setCategory("")}
            />
            {CATEGORIES.map((v) => (
              <Choice
                key={v}
                title={v}
                checked={category === v}
                onPress={() => setCategory(v)}
              />
            ))}
            <Choice
              title="Exclude uncontested events"
              checked={uncontested}
              onPress={() => setUncontested(!uncontested)}
            />
          </View>
          <Text style={[s.section, { color: c.ink }]}>Competition results</Text>
          <ScrollView horizontal contentContainerStyle={s.row}>
            {[
              "date",
              "event",
              "partner",
              "place",
              "field",
              "final",
              "rounds",
            ].map((key) => (
              <Button
                key={key}
                quiet={sort !== key}
                title={key + (sort === key ? (descending ? " ↓" : " ↑") : "")}
                onPress={() => {
                  if (sort === key) setDescending(!descending);
                  else {
                    setSort(key);
                    setDescending(
                      ["date", "field", "final", "rounds"].includes(key),
                    );
                  }
                }}
              />
            ))}
          </ScrollView>
          <Note>
            {rows.length} matching results. Tap an event for its official
            scoresheet.
          </Note>
          {rows.slice(0, limit).map((e, index) => (
            <Pressable
              key={`${e.source}-${e.cid}-${e.eid}-${index}`}
              accessibilityRole="link"
              onPress={() =>
                Linking.openURL(e.url).catch((err) =>
                  setError(errorMessage(err)),
                )
              }
              style={[s.card, { borderColor: c.line }]}
            >
              <Text style={[s.title, { color: c.ink }]}>{e.event}</Text>
              <Note>
                {e.comp} · {e.date || "Date unavailable"}
              </Note>
              <View style={[s.row, { justifyContent: "space-between" }]}>
                <Text style={{ color: c.ink }}>{e.partner || "(solo)"}</Text>
                <Text
                  style={{
                    color: e.place !== null && e.place <= 3 ? c.green : c.ink,
                    fontSize: 21,
                    fontWeight: "600",
                  }}
                >
                  {e.place ?? "—"} / {e.entries ?? "—"}
                </Text>
              </View>
              <Note>
                {e.category} · {e.made_final ? "Finalist" : "Before final"} ·{" "}
                {e.rounds_danced ?? "—"} rounds
              </Note>
            </Pressable>
          ))}
          {rows.length > limit && (
            <Button
              title="Show 50 more results"
              quiet
              onPress={() => setLimit(limit + 50)}
            />
          )}
          <Note>{data.warnings.join(" ")}</Note>
        </>
      )}
    </ScrollView>
  );
}
