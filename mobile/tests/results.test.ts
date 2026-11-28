import assert from "node:assert/strict";
import test from "node:test";
import {
  analysisParams,
  callbackCode,
  filterEvents,
  resultError,
  summarize,
} from "../src/results";
import type { EventResult } from "../src/types";
const events = [
  {
    style: "International Standard",
    cid: 1,
    category: "Couple-judged",
    entries: 1,
    place: 1,
    made_final: true,
    percentile: 100,
  },
  {
    style: "International Latin",
    cid: "o2cm:mit26",
    category: "Solo proficiency follows",
    entries: 8,
    place: 2,
    made_final: true,
    percentile: 85.7,
  },
  {
    style: "Country",
    cid: 1,
    category: "Couple-judged",
    entries: 4,
    place: null,
    made_final: false,
    percentile: null,
  },
] as EventResult[];
test("search accepts IDs, selected profiles, and exact partnerships", () => {
  assert.equal(analysisParams("10062", "", "individual").aid, 10062);
  assert.equal(analysisParams("Sam Moran", "", "individual", 10062).aid, 10062);
  assert.equal(
    analysisParams("Sam Moran", " Melody Yang ", "couple").partner,
    "Melody Yang",
  );
  assert.equal(
    analysisParams("Sam Moran", "Ignored", "individual").partner,
    "",
  );
  assert.throws(() => analysisParams("", "", "individual"));
  assert.throws(() => analysisParams("Sam Moran", "", "couple"));
  assert.throws(() => analysisParams("Sam Moran", "sam moran", "couple"));
});
test("multiple styles union across providers, with compound filters and unknown placements", () => {
  assert.equal(filterEvents(events, [], "", "", false).length, 3);
  assert.equal(
    filterEvents(
      events,
      ["International Standard", "International Latin"],
      "",
      "",
      false,
    ).length,
    2,
  );
  assert.equal(filterEvents(events, [], "", "", true).length, 2);
  assert.equal(
    filterEvents(events, [], "o2cm:mit26", "Solo proficiency follows", true)
      .length,
    1,
  );
  assert.deepEqual(summarize(events), {
    events: 3,
    wins: 1,
    podiums: 2,
    finals: 2,
    field: 93,
  });
});
test("OAuth accepts only the exact app callback and rejects provider errors", () => {
  assert.equal(
    callbackCode("com.sammoran.ballroomstats://auth/callback?code=expected"),
    "expected",
  );
  assert.equal(
    callbackCode("https://evil.example/auth/callback?code=bad"),
    null,
  );
  assert.equal(
    callbackCode("com.sammoran.ballroomstats://auth/other?code=bad"),
    null,
  );
  assert.equal(
    callbackCode("com.sammoran.ballroomstats://different/callback?code=bad"),
    null,
  );
  assert.throws(() =>
    callbackCode(
      "com.sammoran.ballroomstats://auth/callback?error=access_denied",
    ),
  );
});
test("empty couple result has useful feedback", () => {
  assert.match(
    resultError({
      analysis_mode: "couple",
      status: "no_couple_results",
    } as any)!,
    /shared results/,
  );
});
