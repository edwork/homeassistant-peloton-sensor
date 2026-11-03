import { describe, expect, it } from "vitest";
import { DASH } from "../src/format";
import { resolve } from "../src/resolve";
import type { CardView, HomeAssistant, MetricKey, Phase } from "../src/types";
import { announcement, cardSize, computeView, gridOptions, sampleSignal } from "../src/view";
import {
  config,
  entityIdOf,
  type Fixture,
  formatters,
  hassFromFixture,
  hassWith,
  makeHass,
  type RiderOptions,
  rider,
  seededRandom,
} from "./fake-hass";

const START = "2026-11-02T16:00:00+00:00";
const END = "2026-11-02T16:45:00+00:00";

const CYCLING = {
  workout_type: "cycling",
  ride_title: "30 min Pop Ride",
  instructor: "Alex",
  workout_image: "https://example.com/image.png",
  paused: false,
};

/** States of a ride with samples: output, cadence and resistance, no heart rate. */
const RIDING: RiderOptions["states"] = {
  workout: "on",
  start_time: START,
  output_current: "182",
  output_average: "150",
  output_max: "301",
  cadence_current: "85",
  cadence_average: "80",
  cadence_max: "110",
  resistance_current: "40",
  resistance_average: "38",
  resistance_max: "55",
  total_output: "120",
  distance: "5.2",
  total_calories: "210",
  duration: "30",
  leaderboard_rank: "1234",
  leaderboard_total_users: "5678",
};

function viewOf(options: RiderOptions, raw: Record<string, unknown> = {}): CardView {
  return computeView(hassWith(options), config(raw));
}

function keys(view: CardView): MetricKey[] {
  return view.tiles.map((tile) => tile.key);
}

describe("phases", () => {
  it.each([
    ["hass is undefined", undefined],
    ["the entity registry is null", { states: {}, entities: null, devices: {} }],
    ["the device registry is null", { states: {}, entities: {}, devices: null }],
  ])("is loading when %s", (_name, hass) => {
    const view = computeView(hass, config());
    expect(view.phase).toBe("loading");
    expect(view.header).toBeNull();
    expect(view.message).toBeNull();
    expect(view.action).toBeNull();
    expect(view.compact.text).toBe("");
    expect(view.watched).toEqual([]);
  });

  it.each([
    [
      "no_device",
      makeHass({ riders: [] }),
      {},
      "No Peloton account found. Add the Peloton integration first.",
      "No Peloton account",
    ],
    [
      "choose_device",
      makeHass({ riders: [rider(), rider({ deviceId: "device-2" })] }),
      {},
      "Choose a Peloton account in the card settings.",
      "Choose a Peloton account",
    ],
    [
      "device_not_found",
      hassWith(),
      { device_id: "gone" },
      "The selected Peloton account was not found.",
      "Peloton account not found",
    ],
    [
      "device_disabled",
      hassWith({ disabled: true }),
      { device_id: "device-1" },
      "The selected Peloton account is disabled.",
      "Peloton account disabled",
    ],
    [
      "workout_missing",
      hassWith({ disabledKeys: ["workout"] }),
      {},
      "The Peloton workout sensor is disabled or not set up yet.",
      "Workout sensor not available",
    ],
  ])("shows the %s problem", (status, hass, raw, message, short) => {
    const view = computeView(hass, config(raw));
    expect(view.phase).toBe("problem");
    expect(view.problem).toBe(status);
    expect(view.message).toBe(message);
    expect(view.header).toBeNull();
    expect(view.action).toBeNull();
    expect(view.tiles).toEqual([]);
    expect(view.compact).toEqual({
      icon: "mdi:alert-circle-outline",
      tone: "warning",
      text: short,
    });
  });

  it("is waiting when the workout sensor has no state yet", () => {
    const view = viewOf({ noState: ["workout"] });
    expect(view.phase).toBe("waiting");
    expect(view.header).toEqual({
      name: "Jane on Peloton",
      icon: null,
      title: null,
      classLine: null,
      chip: null,
    });
    expect(view.message).toBe("Waiting for Peloton data.");
    expect(view.compact.text).toBe("Waiting for Peloton data");
    expect(view.action).toEqual({
      entity: entityIdOf("workout"),
      tap_action: { action: "more-info" },
    });
  });

  it.each(["unavailable", "unknown", "running", ""])(
    "is unavailable when the workout state is %j",
    (state) => {
      const view = viewOf({ states: { workout: state }, workout: CYCLING });
      expect(view.phase).toBe("unavailable");
      expect(view.header?.chip).toEqual({ text: "Unavailable", tone: "unavailable" });
      expect(view.header?.title).toBeNull();
      expect(view.message).toBe(
        "Peloton data is unavailable. Values return when the connection recovers.",
      );
      expect(view.tiles).toEqual([]);
      expect(view.compact).toMatchObject({ tone: "unavailable", text: "Unavailable" });
    },
  );

  it("shows no workouts, with the total when known", () => {
    const view = viewOf({ states: { workout: "off", total_workouts: "0" }, workout: {} });
    expect(view.phase).toBe("none");
    expect(view.message).toBe("No workouts yet.");
    expect(view.detail).toMatchObject({
      key: "total_workouts",
      label: "Total workouts",
      entityId: entityIdOf("total_workouts"),
    });
    expect(view.detail?.value.text).toBe("0");
    expect(view.compact.text).toBe("No workouts yet");
    expect(view.tiles).toEqual([]);
    expect(viewOf({ states: { workout: "off" }, workout: { workout_type: 5 } }).detail).toBeNull();
  });

  it.each([
    ["on", { paused: true }, "paused"],
    ["on", { paused: "true" }, "active"],
    ["on", { paused: 1 }, "active"],
    ["on", {}, "active"],
    ["off", {}, "idle"],
    ["off", { paused: true }, "idle"],
  ])("with state %s and %j is %s", (state, extra, phase) => {
    expect(viewOf({ states: { workout: state }, workout: { ...CYCLING, ...extra } }).phase).toBe(
      phase,
    );
  });

  it("is active without a workout type", () => {
    const view = viewOf({ states: { workout: "on" }, workout: {} });
    expect(view.phase).toBe("active");
    expect(view.header?.title).toBe("Workout");
    expect(view.header?.icon).toBe("mdi:bike");
    expect(keys(view)).toEqual(["output", "cadence", "resistance", "heart_rate"]);
    expect(view.hint).toBeNull();
  });
});

describe("tiles", () => {
  it("shows all candidates as dashes before the first sample, with the hint", () => {
    const view = viewOf({
      states: { workout: "on", start_time: START, total_calories: "0" },
      workout: CYCLING,
    });
    expect(keys(view)).toEqual(["output", "cadence", "resistance", "heart_rate"]);
    expect(view.tiles.every((tile) => tile.value.text === DASH && !tile.value.known)).toBe(true);
    expect(view.tiles[0].value.label).toBe("No value");
    expect(view.hint).toBe("Waiting for the first data from Peloton");
    expect(view.compact.text).toBe("In progress");
  });

  it("shows strength in progress without metrics and without the hint", () => {
    const view = viewOf({ states: { workout: "on" }, workout: { workout_type: "strength" } });
    expect(keys(view)).toEqual(["heart_rate"]);
    expect(view.tiles[0].value.text).toBe(DASH);
    expect(view.hint).toBeNull();
    expect(view.header?.icon).toBe("mdi:dumbbell");
  });

  it("shows the current value with average and max while active", () => {
    const view = viewOf({ states: RIDING, workout: CYCLING });
    expect(view.phase).toBe("active");
    expect(keys(view)).toEqual(["output", "cadence", "resistance"]);
    const [output, cadence] = view.tiles;
    expect(output).toMatchObject({
      key: "output",
      label: "Output",
      valueLabel: null,
      secondaryText: "Avg 150 W \u00b7 Max 301 W",
      entityId: entityIdOf("output_current"),
      primary: true,
    });
    expect(output.value.parts).toEqual([
      { type: "value", value: "182" },
      { type: "literal", value: " " },
      { type: "unit", value: "W" },
    ]);
    expect(output.secondary.map((item) => [item.label, item.entityId])).toEqual([
      ["Avg", entityIdOf("output_average")],
      ["Max", entityIdOf("output_max")],
    ]);
    expect(cadence.primary).toBe(false);
    expect(view.tilesMuted).toBe(false);
    expect(view.hint).toBeNull();
    expect(view.compact).toEqual({
      icon: "mdi:bike",
      tone: "active",
      text: "In progress: 182 W, 85 rpm",
    });
  });

  it("adds a tile when a sensor starts reporting mid-ride", () => {
    const view = viewOf({ states: { ...RIDING, heart_rate_current: "120" }, workout: CYCLING });
    expect(keys(view)).toEqual(["output", "cadence", "resistance", "heart_rate"]);
    expect(view.tiles[3].secondaryText).toBe(`Avg ${DASH} \u00b7 Max ${DASH}`);
  });

  it("shows averages while paused", () => {
    const view = viewOf({
      states: { ...RIDING, output_current: "0", leaderboard_rank: "unknown" },
      workout: { ...CYCLING, paused: true },
    });
    expect(view.phase).toBe("paused");
    expect(keys(view)).toEqual(["output", "cadence", "resistance"]);
    expect(view.tiles[0]).toMatchObject({
      valueLabel: "Avg",
      secondaryText: "Max 301 W",
      entityId: entityIdOf("output_average"),
    });
    expect(view.tiles[0].value.text).toBe("150 W");
    expect(view.tilesMuted).toBe(true);
    expect(view.hint).toBeNull();
    expect(view.header?.chip).toEqual({ text: "Paused", tone: "paused" });
    expect(view.compact).toMatchObject({ tone: "paused", text: "Paused" });
    // The rank goes unknown after the first pause; the leaderboard disappears.
    expect(view.leaderboard).toBeNull();
    expect(view.leaderboardEntityId).toBeNull();
  });

  it("shows all candidates while paused before the first sample", () => {
    const view = viewOf({ states: { workout: "on" }, workout: { ...CYCLING, paused: true } });
    expect(keys(view)).toEqual(["output", "cadence", "resistance", "heart_rate"]);
    expect(view.hint).toBeNull();
  });

  it("drops metrics without an average between workouts", () => {
    const view = viewOf({
      states: { ...RIDING, workout: "off", end_time: END, output_current: "0" },
      workout: CYCLING,
    });
    expect(view.phase).toBe("idle");
    expect(keys(view)).toEqual(["output", "cadence", "resistance"]);
    expect(view.tiles[0].value.text).toBe("150 W");
    expect(view.header?.chip).toEqual({ text: "Last workout", tone: "idle" });
    expect(view.tilesMuted).toBe(false);
    const empty = viewOf({ states: { workout: "off" }, workout: CYCLING });
    expect(empty.tiles).toEqual([]);
  });

  it.each([
    ["active", "on", false],
    ["paused", "on", true],
    ["idle", "off", false],
  ])("keeps dash tiles for explicit metrics while %s", (phase, state, paused) => {
    const view = viewOf(
      { states: { ...RIDING, workout: state }, workout: { ...CYCLING, paused } },
      { metrics: ["heart_rate", "output", "speed"] },
    );
    expect(view.phase).toBe(phase);
    expect(keys(view)).toEqual(["heart_rate", "output", "speed"]);
    expect(view.tiles[0].value.text).toBe(DASH);
    expect(view.tiles[0].primary).toBe(true);
  });

  it("drops a metric whose sensors are all disabled, even when explicit", () => {
    const disabledKeys = ["cadence_current", "cadence_average", "cadence_max"];
    expect(keys(viewOf({ states: RIDING, workout: CYCLING, disabledKeys }))).toEqual([
      "output",
      "resistance",
    ]);
    const explicit = viewOf(
      { states: RIDING, workout: CYCLING, disabledKeys },
      { metrics: ["cadence", "output"] },
    );
    expect(keys(explicit)).toEqual(["output"]);
  });

  it("falls back to the next mapped sensor for the tap target", () => {
    const active = viewOf(
      {
        states: RIDING,
        workout: CYCLING,
        disabledKeys: ["output_current", "cadence_current", "cadence_average"],
      },
      { metrics: ["output", "cadence"] },
    );
    expect(active.tiles[0].entityId).toBe(entityIdOf("output_average"));
    expect(active.tiles[0].value.text).toBe(DASH);
    expect(active.tiles[0].secondaryText).toBe("Avg 150 W \u00b7 Max 301 W");
    expect(active.tiles[1].entityId).toBe(entityIdOf("cadence_max"));
    expect(active.tiles[1].secondaryText).toBe("Max 110 rpm");
    const idle = viewOf(
      {
        states: { ...RIDING, workout: "off" },
        workout: CYCLING,
        disabledKeys: ["output_average", "output_max"],
      },
      { metrics: ["output"] },
    );
    expect(idle.tiles[0].entityId).toBe(entityIdOf("output_current"));
    expect(idle.tiles[0].secondary).toEqual([]);
    expect(idle.tiles[0].secondaryText).toBe("");
  });

  it("formats tread paces as m:ss with Best", () => {
    const states = {
      workout: "on",
      speed_current: "6.5",
      speed_average: "6.0",
      speed_max: "7.2",
      pace_current: "9.231",
      pace_average: "10",
      pace_max: "8.333",
      incline_current: "1",
      incline_average: "1.5",
      incline_max: "3",
    };
    const view = viewOf({ states, workout: { workout_type: "running" } });
    expect(keys(view)).toEqual(["speed", "pace", "incline"]);
    const pace = view.tiles[1];
    expect(pace.value.text).toBe("9:14/mi");
    expect(pace.secondaryText).toBe("Avg 10:00/mi \u00b7 Best 8:20/mi");
    expect(view.tiles[2].value.text).toBe("1%");
    expect(view.header?.icon).toBe("mdi:run");
  });

  it("shows rower metrics with split pace", () => {
    const states = {
      workout: "on",
      output_current: "150",
      output_average: "140",
      stroke_rate_current: "24",
      stroke_rate_average: "22",
      split_pace_current: "2.05",
      split_pace_average: "2.1",
      split_pace_max: "1.95",
    };
    const view = viewOf({ states, workout: { workout_type: "caesar", ride_title: "Row" } });
    expect(keys(view)).toEqual(["output", "stroke_rate", "split_pace"]);
    expect(view.tiles[2].value.text).toBe("2:03/500m");
    expect(view.tiles[2].secondaryText).toBe("Avg 2:06/500m \u00b7 Best 1:57/500m");
    expect(view.header?.icon).toBe("mdi:rowing");
    expect(view.header?.classLine).toBe("Rowing");
  });
});

describe("header, totals, leaderboard and image", () => {
  it("shows the class while active", () => {
    const view = viewOf({ states: RIDING, workout: CYCLING });
    expect(view.header).toEqual({
      name: "Jane on Peloton",
      icon: "mdi:bike",
      title: "30 min Pop Ride",
      classLine: `Alex \u00b7 Cycling \u00b7 at ${START}`,
      chip: { text: "In progress", tone: "active" },
    });
    expect(view.announce).toBe("Workout started");
  });

  it("shows Just Ride without an instructor", () => {
    const view = viewOf({
      states: RIDING,
      workout: { workout_type: "cycling", ride_title: "Just Ride", instructor: null },
    });
    expect(view.header?.title).toBe("Just Ride");
    expect(view.header?.classLine).toBe(`Cycling \u00b7 at ${START}`);
  });

  it("uses the discipline name when there is no title", () => {
    const view = viewOf({
      states: { workout: "on" },
      workout: { workout_type: "bike_bootcamp", ride_title: 5, instructor: ["x"] },
    });
    expect(view.header?.title).toBe("Bike bootcamp");
    expect(view.header?.classLine).toBe("Bike bootcamp");
    const blank = viewOf({
      states: { workout: "on" },
      workout: { workout_type: "yoga", ride_title: "  " },
    });
    expect(blank.header?.title).toBe("Yoga");
  });

  it("title-cases a workout type without translation", () => {
    const view = viewOf({ states: { workout: "off" }, workout: { workout_type: "outdoor_run" } });
    expect(view.header?.title).toBe("Outdoor run");
    expect(view.compact.text).toBe("Last workout: Outdoor run");
  });

  it("ends the class line with the end time between workouts", () => {
    const view = viewOf({
      states: { ...RIDING, workout: "off", end_time: END },
      workout: CYCLING,
    });
    expect(view.header?.classLine).toBe(`Alex \u00b7 Cycling \u00b7 Ended at ${END}`);
    expect(view.compact).toEqual({
      icon: "mdi:bike",
      tone: "idle",
      text: `Last workout: Cycling, at ${END}`,
    });
    expect(view.announce).toBe("Workout finished");
    const noEnd = viewOf({ states: { ...RIDING, workout: "off" }, workout: CYCLING });
    expect(noEnd.header?.classLine).toBe(`Alex \u00b7 Cycling \u00b7 at ${START}`);
    expect(noEnd.compact.text).toBe(`Last workout: Cycling, at ${START}`);
    const typeOnly = viewOf({ states: { workout: "off" }, workout: { workout_type: "" } });
    expect(typeOnly.compact.text).toBe("Last workout: Workout");
    expect(typeOnly.header?.classLine).toBeNull();
  });

  it("shows the totals and the leaderboard", () => {
    const view = viewOf({ states: RIDING, workout: CYCLING });
    expect(view.totals.map((item) => [item.key, item.label, item.value.text])).toEqual([
      ["total_output", "Total output", "120 kJ"],
      ["distance", "Distance", "5.2 mi"],
      ["total_calories", "Calories", "210 kcal"],
      ["duration", "Class length", "30 min"],
    ]);
    expect(view.totals[0].entityId).toBe(entityIdOf("total_output"));
    expect(view.leaderboard).toBe("Rank 1234 of 5678");
    expect(view.leaderboardEntityId).toBe(entityIdOf("leaderboard_rank"));
  });

  it("hides totals and leaderboard when turned off, and drops unmapped totals", () => {
    const off = viewOf(
      { states: RIDING, workout: CYCLING },
      { show_totals: false, show_leaderboard: false },
    );
    expect(off.totals).toEqual([]);
    expect(off.leaderboard).toBeNull();
    const partial = viewOf({
      states: { ...RIDING, distance: "unknown" },
      workout: CYCLING,
      disabledKeys: ["total_output", "leaderboard_total_users"],
    });
    expect(partial.totals.map((item) => item.key)).toEqual([
      "distance",
      "total_calories",
      "duration",
    ]);
    expect(partial.totals[0].value.text).toBe(DASH);
    expect(partial.leaderboard).toBeNull();
  });

  it("shows only https class images in the full variant", () => {
    expect(viewOf({ states: RIDING, workout: CYCLING }).image).toBe(CYCLING.workout_image);
    for (const workout_image of ["http://example.com/a.png", "javascript:alert(1)", 5, null, ""]) {
      expect(viewOf({ states: RIDING, workout: { ...CYCLING, workout_image } }).image).toBeNull();
    }
    expect(viewOf({ states: RIDING, workout: CYCLING }, { show_image: false }).image).toBeNull();
    expect(viewOf({ states: RIDING, workout: CYCLING }, { variant: "compact" }).image).toBeNull();
    const idle = viewOf({ states: { ...RIDING, workout: "off" }, workout: CYCLING });
    expect(idle.image).toBe(CYCLING.workout_image);
    const unavailable = viewOf({ states: { workout: "unavailable" }, workout: CYCLING });
    expect(unavailable.image).toBeNull();
  });

  it("keeps Peloton text as plain strings", () => {
    const title = "<b>Bold</b><img src=x onerror=alert(1)>";
    const view = viewOf({ states: RIDING, workout: { ...CYCLING, ride_title: title } });
    expect(view.header?.title).toBe(title);
  });

  it("uses the configured name and tap action", () => {
    const tap = { action: "navigate", navigation_path: "/peloton" };
    const view = viewOf({ states: RIDING, workout: CYCLING }, { name: "Jane", tap_action: tap });
    expect(view.header?.name).toBe("Jane");
    expect(view.action).toEqual({ entity: entityIdOf("workout"), tap_action: tap });
    expect(view.variant).toBe("full");
    expect(viewOf({ states: RIDING, workout: CYCLING }, { variant: "compact" }).variant).toBe(
      "compact",
    );
  });

  it("watches the resolved entities", () => {
    const hass = hassWith({ states: RIDING, workout: CYCLING });
    const cfg = config();
    const resolution = resolve(hass, cfg);
    expect(resolution.status).toBe("ok");
    if (resolution.status === "ok") expect(computeView(hass, cfg).watched).toBe(resolution.watched);
  });
});

describe("without formatters", () => {
  it("falls back to states and units", () => {
    const hass = hassWith({ states: RIDING, workout: CYCLING }, { withFormatters: false });
    const view = computeView(hass, config());
    expect(view.tiles[0].value.text).toBe("182 W");
    expect(view.tiles[2].value.text).toBe("40%");
    expect(view.header?.classLine).toMatch(/^Alex \u00b7 Cycling \u00b7 Nov 2, 2026/);
  });
});

describe("config handling", () => {
  it("normalizes a raw or missing config", () => {
    const hass = hassWith({ states: RIDING, workout: CYCLING });
    expect(computeView(hass, undefined as never).variant).toBe("full");
    expect(computeView(hass, { variant: "compact" } as never).variant).toBe("compact");
    expect(computeView(hass, { variant: "huge" } as never).variant).toBe("full");
  });
});

describe("announcement", () => {
  it.each<[Phase | undefined, Phase, string | null]>([
    [undefined, "active", null],
    ["active", "active", null],
    ["idle", "active", "Workout started"],
    ["none", "active", "Workout started"],
    ["paused", "active", "Workout resumed"],
    ["active", "paused", "Workout paused"],
    ["idle", "paused", "Workout paused"],
    ["active", "idle", "Workout finished"],
    ["paused", "idle", "Workout finished"],
    ["loading", "idle", null],
    ["unavailable", "active", null],
    ["waiting", "active", null],
    ["active", "unavailable", null],
    ["idle", "none", null],
  ])("from %s to %s is %s", (previous, next, text) => {
    expect(announcement(undefined, previous, next)).toBe(text);
  });

  it("is set on the workout phases only", () => {
    expect(
      viewOf({ states: { workout: "on" }, workout: { ...CYCLING, paused: true } }).announce,
    ).toBe("Workout paused");
    expect(viewOf({ states: { workout: "unavailable" } }).announce).toBeNull();
  });
});

describe("layout", () => {
  it("returns the grid options per variant", () => {
    expect(gridOptions(config())).toEqual({
      columns: 12,
      rows: "auto",
      min_columns: 6,
      min_rows: 3,
    });
    expect(gridOptions(config({ variant: "compact" }))).toEqual({
      columns: 6,
      rows: 1,
      min_columns: 3,
      max_rows: 2,
    });
  });

  it("estimates the masonry card size", () => {
    const tiles = (count: number) => ({
      tiles: Array.from({ length: count }) as CardView["tiles"],
    });
    expect(cardSize(config(), undefined)).toBe(3);
    expect(cardSize(config({ show_totals: false }), tiles(0))).toBe(2);
    expect(cardSize(config(), tiles(4))).toBe(5);
    expect(cardSize(config(), tiles(5))).toBe(7);
    expect(cardSize(config({ show_totals: false }), tiles(3))).toBe(4);
    expect(cardSize(config({ variant: "compact" }), tiles(4))).toBe(1);
  });
});

describe("sampleSignal", () => {
  it("counts averages, total output and distance, not calories", () => {
    const { map } = resolve(hassWith(), config()) as { map: Record<string, string> };
    expect(sampleSignal(hassWith({ states: { total_calories: "0" } }), map)).toBe(false);
    expect(sampleSignal(hassWith({ states: { heart_rate_current: "90" } }), map)).toBe(false);
    expect(sampleSignal(hassWith({ states: { stroke_rate_average: "20" } }), map)).toBe(true);
    expect(sampleSignal(hassWith({ states: { total_output: "1" } }), map)).toBe(true);
    expect(sampleSignal(hassWith({ states: { distance: "0.1" } }), map)).toBe(true);
  });
});

// Contract fixtures written by tests/test_card_fixtures.py from the real
// integration (rewrite them with PELOTON_UPDATE_CARD_FIXTURES=1). Each file is
// checked against the invariants below and against its row in
// FIXTURE_EXPECTATIONS. A renamed attribute or translation key fails pytest
// first, then these tests.
interface FixtureExpectation {
  phase: Phase;
  /** Header title; null when the phase has none. */
  title: string | null;
  icon: string | null;
  chip: string | null;
  classLine: string | null;
  message: string | null;
  hint: boolean;
  /** Tiles in order, with the text of the large value and the second line. */
  tiles: [MetricKey, string, string][];
  /** Totals in order, with their text. */
  totals: [string, string][];
  leaderboard: string | null;
  image: string | null;
  compact: string;
}

const F_START = "2025-10-09T08:53:20+00:00";
const F_END = "2025-10-09T09:23:20+00:00";
const F_TITLE = "30 min Synthetic Ride";
const F_IMAGE = "https://example.invalid/ride.png";
const F_WORKOUT = "binary_sensor.test_on_peloton_workout";
const DOT = " \u00b7 ";
const NO_WORKOUT: Omit<FixtureExpectation, "phase" | "chip" | "message" | "compact"> = {
  title: null,
  icon: null,
  classLine: null,
  hint: false,
  tiles: [],
  totals: [],
  leaderboard: null,
  image: null,
};
const CYCLING_TOTALS: [string, string][] = [
  ["total_output", "360 kJ"],
  ["distance", "10.5 mi"],
  ["total_calories", "450 kcal"],
  ["duration", "30.0 min"],
];
const CYCLING_AVERAGES: [MetricKey, string, string][] = [
  ["output", "200 W", "Max 320 W"],
  ["cadence", "85 rpm", "Max 110 rpm"],
  ["resistance", "42%", "Max 60%"],
  ["heart_rate", "140 bpm", "Max 165 bpm"],
];
const CYCLING_HEADER = {
  title: F_TITLE,
  icon: "mdi:bike",
  classLine: ["Synthetic Instructor", "Cycling", `at ${F_START}`].join(DOT),
  message: null,
  image: F_IMAGE,
};

const FIXTURE_EXPECTATIONS: Readonly<Record<string, FixtureExpectation>> = {
  no_workouts: {
    ...NO_WORKOUT,
    phase: "none",
    chip: null,
    message: "No workouts yet.",
    compact: "No workouts yet",
  },
  pre_roll: {
    ...CYCLING_HEADER,
    phase: "active",
    chip: "In progress",
    hint: true,
    tiles: [
      ["output", DASH, `Avg ${DASH}${DOT}Max ${DASH}`],
      ["cadence", DASH, `Avg ${DASH}${DOT}Max ${DASH}`],
      ["resistance", DASH, `Avg ${DASH}${DOT}Max ${DASH}`],
      ["heart_rate", DASH, `Avg ${DASH}${DOT}Max ${DASH}`],
    ],
    // Peloton reports 0 calories before the first sample.
    totals: [
      ["total_output", DASH],
      ["distance", DASH],
      ["total_calories", "0 kcal"],
      ["duration", "30.0 min"],
    ],
    leaderboard: null,
    compact: "In progress",
  },
  active_cycling: {
    ...CYCLING_HEADER,
    phase: "active",
    chip: "In progress",
    hint: false,
    tiles: [
      ["output", "190 W", `Avg 200 W${DOT}Max 320 W`],
      ["cadence", "88 rpm", `Avg 85 rpm${DOT}Max 110 rpm`],
      ["resistance", "44%", `Avg 42%${DOT}Max 60%`],
      ["heart_rate", "148 bpm", `Avg 140 bpm${DOT}Max 165 bpm`],
    ],
    totals: CYCLING_TOTALS,
    leaderboard: "Rank 120 of 4000",
    compact: "In progress: 190 W, 88 rpm",
  },
  paused: {
    ...CYCLING_HEADER,
    phase: "paused",
    chip: "Paused",
    hint: false,
    tiles: CYCLING_AVERAGES,
    totals: CYCLING_TOTALS,
    // Peloton drops the rank after the first pause.
    leaderboard: null,
    compact: "Paused",
  },
  finished_cycling: {
    ...CYCLING_HEADER,
    phase: "idle",
    chip: "Last workout",
    classLine: ["Synthetic Instructor", "Cycling", `Ended at ${F_END}`].join(DOT),
    hint: false,
    tiles: CYCLING_AVERAGES,
    totals: CYCLING_TOTALS,
    leaderboard: "Rank 120 of 4000",
    compact: `Last workout: Cycling, at ${F_END}`,
  },
  strength_in_progress: {
    ...CYCLING_HEADER,
    phase: "active",
    icon: "mdi:dumbbell",
    chip: "In progress",
    classLine: ["Synthetic Instructor", "Strength", `at ${F_START}`].join(DOT),
    hint: false,
    tiles: [["heart_rate", DASH, `Avg ${DASH}${DOT}Max ${DASH}`]],
    totals: [
      ["total_output", DASH],
      ["distance", DASH],
      ["total_calories", DASH],
      ["duration", "30.0 min"],
    ],
    leaderboard: null,
    compact: "In progress",
  },
  rower: {
    ...CYCLING_HEADER,
    phase: "idle",
    icon: "mdi:rowing",
    chip: "Last workout",
    classLine: ["Synthetic Instructor", "Rowing", `Ended at ${F_END}`].join(DOT),
    hint: false,
    tiles: [
      ["output", "125 W", "Max 210 W"],
      ["stroke_rate", "24 spm", "Max 30 spm"],
      ["split_pace", "3:39/500m", "Best 2:43/500m"],
    ],
    totals: [
      ["total_output", "150 kJ"],
      ["distance", "2.5 mi"],
      ["total_calories", "200 kcal"],
      ["duration", "30.0 min"],
    ],
    leaderboard: "Rank 120 of 4000",
    compact: `Last workout: Rowing, at ${F_END}`,
  },
  tread: {
    ...CYCLING_HEADER,
    phase: "active",
    icon: "mdi:run",
    chip: "In progress",
    classLine: ["Synthetic Instructor", "Running", `at ${F_START}`].join(DOT),
    hint: false,
    tiles: [
      ["speed", "6.0 mph", `Avg 5.2 mph${DOT}Max 7.06 mph`],
      ["pace", "10:00/mi", `Avg 11:26/mi${DOT}Best 8:30/mi`],
      ["incline", "4.5%", `Avg 3.0%${DOT}Max 12.0%`],
    ],
    totals: [
      ["total_output", "96 kJ"],
      ["distance", "2.0 mi"],
      ["total_calories", "156 kcal"],
      ["duration", "30.0 min"],
    ],
    leaderboard: "Rank 120 of 4000",
    compact: "In progress: 6.0 mph, 10:00/mi",
  },
  unavailable: {
    ...NO_WORKOUT,
    phase: "unavailable",
    chip: "Unavailable",
    message: "Peloton data is unavailable. Values return when the connection recovers.",
    compact: "Unavailable",
  },
  disabled_metric: {
    ...CYCLING_HEADER,
    phase: "active",
    chip: "In progress",
    hint: false,
    // The cadence sensors are disabled, so they are not in hass at all.
    tiles: [
      ["output", "190 W", `Avg 200 W${DOT}Max 320 W`],
      ["resistance", "44%", `Avg 42%${DOT}Max 60%`],
      ["heart_rate", "148 bpm", `Avg 140 bpm${DOT}Max 165 bpm`],
    ],
    totals: CYCLING_TOTALS,
    leaderboard: "Rank 120 of 4000",
    compact: "In progress: 190 W, 44%",
  },
};

// Globbed in this file: from fake-hass.ts, which awaits an import at top
// level, the glob comes back empty under `vitest run --coverage`.
const FIXTURES: [string, Fixture][] = Object.entries(
  import.meta.glob<Fixture>("./fixtures/*.json", { eager: true, import: "default" }),
)
  .map(([path, fixture]): [string, Fixture] => [path.replace(/^.*\/|\.json$/g, ""), fixture])
  .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));

describe("contract fixtures", () => {
  it("has one expectation per fixture file", () => {
    expect(FIXTURES.map(([name]) => name)).toEqual(Object.keys(FIXTURE_EXPECTATIONS).sort());
  });

  it.each(FIXTURES)("%s renders within the contract", (name, fixture: Fixture) => {
    const hass = hassFromFixture(fixture);
    const view = computeView(hass, config());
    expect(["loading", "problem"]).not.toContain(view.phase);
    const known = new Set([...Object.keys(fixture.entities), ...Object.keys(fixture.states)]);
    for (const id of view.watched) expect(known).toContain(id);
    for (const tile of view.tiles) expect(known).toContain(tile.entityId);
    expect(() => structuredClone(view)).not.toThrow();

    const expected = FIXTURE_EXPECTATIONS[name];
    expect(view.phase).toBe(expected.phase);
    expect(view.header).toEqual({
      name: "Test on Peloton",
      icon: expected.icon,
      title: expected.title,
      classLine: expected.classLine,
      chip: expected.chip === null ? null : expect.objectContaining({ text: expected.chip }),
    });
    expect(view.message).toBe(expected.message);
    expect(view.hint !== null).toBe(expected.hint);
    expect(view.tiles.map((tile) => [tile.key, tile.value.text, tile.secondaryText])).toEqual(
      expected.tiles,
    );
    expect(view.totals.map((item) => [item.key, item.value.text])).toEqual(expected.totals);
    expect(view.leaderboard).toBe(expected.leaderboard);
    expect(view.image).toBe(expected.image);
    expect(view.compact.text).toBe(expected.compact);
    expect(view.action).toEqual({ entity: F_WORKOUT, tap_action: { action: "more-info" } });
  });

  it("maps the renamed best-pace sensors by translation key", () => {
    const fixture = Object.fromEntries(FIXTURES).tread;
    const view = computeView(hassFromFixture(fixture), config());
    const pace = view.tiles.find((tile) => tile.key === "pace");
    expect(pace?.secondary.map((item) => item.entityId)).toEqual([
      "sensor.test_on_peloton_pace_average",
      "sensor.test_on_peloton_pace_best",
    ]);
  });

  it("taps the averages while paused", () => {
    const fixture = Object.fromEntries(FIXTURES).paused;
    const view = computeView(hassFromFixture(fixture), config());
    expect(view.tiles.map((tile) => tile.entityId)).toEqual([
      "sensor.test_on_peloton_output_average",
      "sensor.test_on_peloton_cadence_average",
      "sensor.test_on_peloton_resistance_average",
      "sensor.test_on_peloton_heart_rate_average",
    ]);
    expect(view.tilesMuted).toBe(true);
  });

  it("shows the total workouts when there are none", () => {
    const fixture = Object.fromEntries(FIXTURES).no_workouts;
    const view = computeView(hassFromFixture(fixture), config());
    expect(view.detail?.value.text).toBe("96");
  });
});

describe("fuzz", () => {
  const random = seededRandom(20261102);
  const pick = <T>(items: readonly T[]): T => items[Math.floor(random() * items.length)];
  const junk: unknown[] = [
    undefined,
    null,
    Number.NaN,
    Number.POSITIVE_INFINITY,
    -1,
    0,
    "",
    "on",
    "off",
    "unknown",
    "unavailable",
    "abc",
    "12.5",
    "-3",
    true,
    [],
    ["x"],
    {},
    { state: "on" },
    "https://example.com/x.png",
    "http://example.com/x.png",
    "<b>x</b>",
    "cycling",
    "caesar",
    "strength",
    "toString",
    "__proto__",
  ];
  const throwing = () => {
    throw new Error("boom");
  };
  const formatterChoices: unknown[] = [undefined, null, 5, throwing, () => junk, () => pick(junk)];

  function mutateRecord(record: Record<string, unknown>): void {
    for (const key of Object.keys(record)) {
      const roll = random();
      if (roll < 0.1) record[key] = pick(junk);
      else if (roll < 0.15) delete record[key];
      else if (roll < 0.4 && typeof record[key] === "object" && record[key] !== null) {
        const inner = record[key] as Record<string, unknown>;
        for (const field of Object.keys(inner)) {
          if (random() < 0.3) inner[field] = pick(junk);
        }
        if (random() < 0.3 && typeof inner.attributes === "object" && inner.attributes) {
          const attrs = inner.attributes as Record<string, unknown>;
          for (const attr of [
            "workout_type",
            "paused",
            "ride_title",
            "instructor",
            "workout_image",
            "unit_of_measurement",
            "device_class",
          ]) {
            if (random() < 0.4) attrs[attr] = pick(junk);
          }
        }
      }
    }
  }

  function randomHass(): unknown {
    const roll = random();
    if (roll < 0.05) return pick(junk);
    const states = pick([
      RIDING,
      { workout: "off" },
      { workout: "on" },
      {},
      { workout: "unavailable" },
    ]);
    const workout = pick<Record<string, unknown>>([
      CYCLING,
      { ...CYCLING, paused: true },
      {},
      { workout_type: "running" },
    ]);
    const riders = [rider({ states, workout })];
    if (random() < 0.2) riders.push(rider({ deviceId: "device-2", prefix: "jane_on_peloton_2" }));
    const hass = makeHass({ riders }) as unknown as Record<string, unknown>;
    for (const name of ["states", "entities", "devices"]) {
      if (random() < 0.5) mutateRecord(hass[name] as Record<string, unknown>);
      if (random() < 0.05) hass[name] = pick(junk);
    }
    for (const name of Object.keys(formatters)) {
      if (random() < 0.3) hass[name] = pick(formatterChoices);
    }
    if (random() < 0.1) hass.locale = pick(junk);
    if (random() < 0.1) hass.language = pick(junk);
    return hass;
  }

  const configs = [
    config(),
    config({ variant: "compact" }),
    config({ metrics: ["pace", "split_pace", "heart_rate"] }),
    config({ device_id: "device-2", show_totals: false, show_leaderboard: false }),
    config({
      entities: {
        workout: "binary_sensor.other",
        pace_current: "sensor.jane_on_peloton_output_current",
      },
    }),
  ];

  it("never throws for 500 malformed hass objects", () => {
    const phases = new Set<Phase>();
    for (let index = 0; index < 500; index++) {
      const hass = randomHass() as HomeAssistant;
      const cfg = pick(configs);
      let view: CardView | undefined;
      expect(() => {
        view = computeView(hass, cfg);
      }, `case ${index}`).not.toThrow();
      if (!view) continue;
      phases.add(view.phase);
      expect(typeof view.compact.text).toBe("string");
      for (const tile of view.tiles) {
        expect(typeof tile.value.text).toBe("string");
        expect(typeof tile.secondaryText).toBe("string");
      }
      expect(() => JSON.stringify(view)).not.toThrow();
    }
    // The generator reaches most phases.
    expect(phases.size).toBeGreaterThanOrEqual(6);
  });
});
