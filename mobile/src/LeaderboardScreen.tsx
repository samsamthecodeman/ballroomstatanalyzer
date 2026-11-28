import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { couples, leaderboard } from "./api";
import { CATEGORIES, STYLES } from "./results";
import type { AnalysisMode, Board, Couple } from "./types";
import { errorMessage, toggle } from "./AnalysisScreen";
import { Button, Choice, Heading, Input, Note, s, usePalette } from "./ui";
export default function LeaderboardScreen() {
  const c = usePalette(),
    request = useRef<AbortController | null>(null);
  const [mode, setMode] = useState<AnalysisMode>("individual"),
    [region, setRegion] = useState("texas"),
    [styles, setStyles] = useState<string[]>([]);
  const [query, setQuery] = useState(""),
    [year, setYear] = useState(""),
    [level, setLevel] = useState(""),
    [category, setCategory] = useState("Couple-judged"),
    [uncontested, setUncontested] = useState(false);
  const [board, setBoard] = useState<Board | null>(null),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [suggestions, setSuggestions] = useState<Couple[]>([]),
    [limit, setLimit] = useState(50);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (mode !== "couple" || query.trim().length < 3) return;
    const abort = new AbortController(),
      timer = setTimeout(
        () =>
          couples(query.trim(), abort.signal)
            .then((r) => {
              if (!abort.signal.aborted) setSuggestions(r.couples);
            })
            .catch(() => {}),
        500,
      );
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [query, mode]);
  async function load() {
    request.current?.abort();
    const abort = new AbortController();
    request.current = abort;
    setBusy(true);
    setError("");
    try {
      const result = await leaderboard(
        {
          mode,
          region,
          styles: JSON.stringify(styles),
          q: query,
          year,
          level,
          category: mode === "couple" ? "Couple-judged" : category,
          excludeUncontested: String(uncontested),
        },
        abort.signal,
      );
      if (!abort.signal.aborted) {
        setBoard(result);
        setSuggestions([]);
        setLimit(50);
      }
    } catch (err) {
      if (!abort.signal.aborted) setError(errorMessage(err));
    } finally {
      if (request.current === abort) setBusy(false);
    }
  }
  useEffect(() => {
    const abort = new AbortController();
    request.current = abort;
    leaderboard(
      { mode: "individual", region: "texas", category: "Couple-judged" },
      abort.signal,
    )
      .then((data) => {
        if (!abort.signal.aborted) setBoard(data);
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => {
        if (!abort.signal.aborted) setBusy(false);
      });
    return () => abort.abort();
  }, []);
  return (
    <ScrollView
      contentContainerStyle={s.screen}
      keyboardShouldPersistTaps="handled"
    >
      <Heading
        title="The leaderboard."
        subtitle="Total wins. Real partnerships. BCE + O2CM."
      />
      <View style={s.row}>
        {(["individual", "couple"] as const).map((v) => (
          <Choice
            key={v}
            title={v === "individual" ? "Individuals" : "Couples"}
            checked={mode === v}
            onPress={() => {
              setMode(v);
              setSuggestions([]);
            }}
          />
        ))}
        {["texas", "national"].map((v) => (
          <Choice
            key={v}
            title={v === "texas" ? "Texas" : "U.S. national"}
            checked={region === v}
            onPress={() => setRegion(v)}
          />
        ))}
      </View>
      <Text style={[s.section, { color: c.ink }]}>Styles</Text>
      <View style={s.row}>
        {STYLES.map((v) => (
          <Choice
            key={v}
            title={v}
            checked={styles.includes(v)}
            onPress={() => setStyles(toggle(styles, v))}
          />
        ))}
      </View>
      <Note>
        None selected includes all styles. Rankings cover cached competitions
        with verified venues.
      </Note>
      <ScrollView horizontal contentContainerStyle={s.row}>
        <Choice title="All years" checked={!year} onPress={() => setYear("")} />
        {board?.years.map((v) => (
          <Choice
            key={v}
            title={v}
            checked={year === v}
            onPress={() => setYear(v)}
          />
        ))}
      </ScrollView>
      <Text style={[s.note, { color: c.ink }]}>Level</Text>
      <ScrollView horizontal contentContainerStyle={s.row}>
        <Choice
          title="All levels"
          checked={!level}
          onPress={() => setLevel("")}
        />
        {[
          "Newcomer / Beginner",
          "Pre-Bronze",
          "Bronze",
          "Silver",
          "Gold",
          "Novice",
          "Pre-Champ",
          "Championship",
          "Open",
        ].map((v) => (
          <Choice
            key={v}
            title={v}
            checked={level === v}
            onPress={() => setLevel(v)}
          />
        ))}
      </ScrollView>
      {mode === "individual" ? (
        <>
          <Text style={[s.note, { color: c.ink }]}>Category</Text>
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
          </View>
        </>
      ) : (
        <Note>
          Each couple-judged win counts once for the partnership. Different
          partners are ranked separately.
        </Note>
      )}
      <View style={{ height: 16 }} />
      <Input
        accessibilityLabel="Leaderboard name or couple"
        placeholder="Name or couple (3+ letters for suggestions)"
        value={query}
        onChangeText={(v) => {
          setQuery(v);
          setSuggestions([]);
        }}
      />
      {suggestions.slice(0, 5).map((pair) => (
        <Pressable
          key={pair.label}
          accessibilityRole="button"
          onPress={() => {
            setQuery(pair.label);
            setSuggestions([]);
          }}
          style={[s.card, { borderColor: c.line }]}
        >
          <Text style={{ color: c.ink }}>{pair.label}</Text>
        </Pressable>
      ))}
      <Choice
        title="Exclude uncontested events"
        checked={uncontested}
        onPress={() => setUncontested(!uncontested)}
      />
      <View style={{ height: 12 }} />
      <Button
        title={busy ? "Loading…" : "Update leaderboard"}
        disabled={busy}
        onPress={load}
      />
      {error ? <Note error>{error}</Note> : null}
      {busy && <ActivityIndicator color={c.ink} style={{ marginTop: 16 }} />}
      {board && (
        <>
          <Note>
            {board.region === "texas" ? "Texas" : "U.S. national"} ·{" "}
            {board.mode === "couple" ? "Couples" : "Individuals"} ·{" "}
            {board.matching_names} matches · {board.unknown_venues} competitions
            excluded for unknown venue. Apply changes with Update leaderboard.
          </Note>
          {board.rows.slice(0, limit).map((row, index) => (
            <View
              key={`${row.name}-${index}`}
              style={[
                s.card,
                s.row,
                { borderColor: c.line, alignItems: "flex-start" },
              ]}
            >
              <Text style={{ color: c.muted, width: 38, fontSize: 20 }}>
                {row.rank}
              </Text>
              <View style={{ flex: 1 }}>
                <Text style={[s.title, { color: c.ink }]}>{row.name}</Text>
                <Note>
                  {row.events} events · {row.competitions} competitions
                </Note>
              </View>
              <Text style={{ color: c.green, fontSize: 26, fontWeight: "600" }}>
                {row.wins}
              </Text>
            </View>
          ))}
          {board.rows.length > limit && (
            <Button
              title="Show 50 more"
              quiet
              onPress={() => setLimit(limit + 50)}
            />
          )}
          {!board.rows.length && <Note>No results match these filters.</Note>}
        </>
      )}
    </ScrollView>
  );
}
