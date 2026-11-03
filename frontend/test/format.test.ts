import { describe, expect, it } from "vitest";
import {
  autoMetrics,
  DASH,
  DEFAULT_ICON,
  disciplineIcon,
  disciplineName,
  formatStateText,
  formatValue,
  leaderboardText,
  metricDiscipline,
  paceParts,
  paceText,
  titleCase,
  unknownValue,
} from "../src/format";
import { language, localize, TRANSLATIONS } from "../src/localize";
import type { HassEntity } from "../src/types";
import { blueprintWorkoutTypes, formatters, WORKOUT_TYPE_NAMES } from "./fake-hass";

const hass = { language: "en", ...formatters };

function entity(state: string, attributes: Record<string, unknown> = {}): HassEntity {
  return { entity_id: "sensor.x", state, attributes };
}

const SLUGS = [
  "cycling",
  "bike_bootcamp",
  "running",
  "walking",
  "circuit",
  "caesar",
  "caesar_bootcamp",
  "cardio",
  "strength",
  "yoga",
  "stretching",
  "meditation",
];

describe("pace", () => {
  it.each([
    [8.5, "8:30"],
    ["8.5", "8:30"],
    [3.999, "4:00"],
    [1.9999, "2:00"],
    [2.0083, "2:00"],
    [2.0084, "2:01"],
    [0.5, "0:30"],
    [59.999, "60:00"],
    [59.99, "59:59"],
    [12, "12:00"],
  ])("formats %s as %s", (value, text) => {
    expect(paceText(value)).toBe(text);
  });

  it.each([
    [0],
    [-1],
    ["0"],
    ["-3.5"],
    ["abc"],
    [""],
    ["  "],
    [Number.NaN],
    [Number.POSITIVE_INFINITY],
    [null],
    [undefined],
    [{}],
    [0.001],
  ])("has no pace for %s", (value) => {
    expect(paceText(value)).toBeNull();
  });

  it.each([
    ["min/500m", [{ type: "unit", value: "/500m" }]],
    ["min/mi", [{ type: "unit", value: "/mi" }]],
    ["min/km", [{ type: "unit", value: "/km" }]],
    [
      "min/100m",
      [
        { type: "literal", value: " " },
        { type: "unit", value: "min/100m" },
      ],
    ],
    [undefined, []],
    [5, []],
  ])("shows the unit %s", (unit, unitParts) => {
    expect(paceParts(2.5, unit)).toEqual([{ type: "value", value: "2:30" }, ...unitParts]);
  });

  it("formats a pace sensor and dashes a zero pace", () => {
    const view = formatValue(hass, entity("2.25", { unit_of_measurement: "min/500m" }), {
      pace: true,
    });
    expect(view).toMatchObject({ text: "2:15/500m", known: true, label: "2:15/500m" });
    const zero = formatValue(hass, entity("0", { unit_of_measurement: "min/mi" }), { pace: true });
    expect(zero).toMatchObject({ text: DASH, known: false, label: "No value" });
  });
});

describe("formatValue", () => {
  it("uses formatEntityStateToParts", () => {
    const view = formatValue(hass, entity("182", { unit_of_measurement: "W" }));
    expect(view.parts).toEqual([
      { type: "value", value: "182" },
      { type: "literal", value: " " },
      { type: "unit", value: "W" },
    ]);
    expect(view.text).toBe("182 W");
    expect(view.known).toBe(true);
  });

  it("falls back to the state and unit without the formatter", () => {
    expect(formatValue({}, entity("85", { unit_of_measurement: "rpm" })).text).toBe("85 rpm");
    expect(formatValue({}, entity("40", { unit_of_measurement: "%" })).text).toBe("40%");
    expect(formatValue({}, entity("12")).text).toBe("12");
    expect(formatValue(undefined, entity("12", { unit_of_measurement: 5 })).text).toBe("12");
  });

  it.each([
    [
      "throws",
      () => {
        throw new Error("boom");
      },
    ],
    ["returns a string", () => "182 W"],
    ["returns no parts", () => []],
    ["returns bad parts", () => [{ type: "number", value: "1" }]],
    ["returns non-string values", () => [{ type: "value", value: 1 }]],
    ["returns null parts", () => [null]],
  ])("falls back when the formatter %s", (_name, fn) => {
    const view = formatValue(
      { formatEntityStateToParts: fn },
      entity("182", { unit_of_measurement: "W" }),
    );
    expect(view.text).toBe("182 W");
  });

  it("dashes unknown, unavailable, empty and missing states", () => {
    for (const state of [undefined, entity("unknown"), entity("unavailable"), entity("")]) {
      expect(formatValue(hass, state)).toEqual(unknownValue(hass));
    }
    expect(formatValue(hass, entity("x"), {}).known).toBe(true);
    const blank = formatValue(
      { formatEntityStateToParts: () => [{ type: "value", value: " " }] },
      entity("1"),
    );
    expect(blank.known).toBe(false);
    expect(unknownValue(hass)).toEqual({
      parts: [{ type: "value", value: DASH }],
      text: DASH,
      known: false,
      label: "No value",
    });
  });

  it("does not share part objects with the formatter", () => {
    const parts = [{ type: "value" as const, value: "1" }];
    const view = formatValue({ formatEntityStateToParts: () => parts }, entity("1"));
    expect(view.parts[0]).not.toBe(parts[0]);
  });
});

describe("formatStateText", () => {
  it("uses formatEntityState", () => {
    const start = entity("2026-11-02T16:00:00+00:00", { device_class: "timestamp" });
    expect(formatStateText(hass, start)).toBe("at 2026-11-02T16:00:00+00:00");
    expect(formatStateText(hass, entity("unknown"))).toBeNull();
    expect(formatStateText(hass, undefined)).toBeNull();
  });

  it("falls back to the locale date, then ISO, then the state", () => {
    const start = entity("2026-11-02T16:00:00+00:00", { device_class: "timestamp" });
    const expected = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(start.state));
    expect(formatStateText({ language: "en" }, start)).toBe(expected);
    expect(formatStateText({ language: "not a language!" }, start)).toBe(
      "2026-11-02T16:00:00.000Z",
    );
    expect(formatStateText({}, entity("soon", { device_class: "timestamp" }))).toBe("soon");
    expect(formatStateText({}, entity("12"))).toBe("12");
    const throwing = {
      formatEntityState: () => {
        throw new Error("boom");
      },
    };
    expect(formatStateText(throwing, entity("12"))).toBe("12");
    expect(formatStateText({ formatEntityState: () => "" }, entity("12"))).toBe("12");
  });
});

describe("leaderboard", () => {
  it("shows Rank R of T when both are known", () => {
    expect(leaderboardText(hass, entity("1234"), entity("5678"))).toBe("Rank 1234 of 5678");
  });

  it("is hidden when either is unknown", () => {
    expect(leaderboardText(hass, entity("unknown"), entity("5678"))).toBeNull();
    expect(leaderboardText(hass, entity("12"), undefined)).toBeNull();
    expect(leaderboardText(hass, undefined, undefined)).toBeNull();
  });
});

describe("workout types", () => {
  it("covers every workout type of the blueprint", () => {
    expect(new Set(blueprintWorkoutTypes())).toEqual(new Set(SLUGS));
  });

  it.each([
    ["cycling", ["output", "cadence", "resistance", "heart_rate"]],
    ["bike_bootcamp", ["output", "cadence", "resistance", "heart_rate"]],
    ["running", ["speed", "pace", "incline", "heart_rate"]],
    ["walking", ["speed", "pace", "incline", "heart_rate"]],
    ["circuit", ["speed", "pace", "incline", "heart_rate"]],
    ["caesar", ["output", "stroke_rate", "split_pace", "heart_rate"]],
    ["caesar_bootcamp", ["output", "stroke_rate", "split_pace", "heart_rate"]],
    ["strength", ["heart_rate"]],
    ["yoga", ["heart_rate"]],
    ["meditation", ["heart_rate"]],
    ["stretching", ["heart_rate"]],
    ["cardio", ["heart_rate"]],
    ["boxing", ["output", "cadence", "resistance", "heart_rate"]],
    [null, ["output", "cadence", "resistance", "heart_rate"]],
    ["toString", ["output", "cadence", "resistance", "heart_rate"]],
  ])("chooses the automatic metrics for %s", (slug, metrics) => {
    expect(autoMetrics(slug)).toEqual(metrics);
  });

  it("knows which disciplines report metrics", () => {
    expect(SLUGS.filter(metricDiscipline)).toEqual([
      "cycling",
      "bike_bootcamp",
      "running",
      "walking",
      "circuit",
      "caesar",
      "caesar_bootcamp",
    ]);
    expect(metricDiscipline(undefined)).toBe(false);
  });

  it.each([
    ["cycling", "mdi:bike"],
    ["bike_bootcamp", "mdi:bike"],
    ["running", "mdi:run"],
    ["walking", "mdi:walk"],
    ["caesar", "mdi:rowing"],
    ["caesar_bootcamp", "mdi:rowing"],
    ["circuit", "mdi:run-fast"],
    ["strength", "mdi:dumbbell"],
    ["yoga", "mdi:yoga"],
    ["meditation", "mdi:meditation"],
    ["stretching", "mdi:human-handsup"],
    ["cardio", "mdi:heart-pulse"],
    ["boxing", DEFAULT_ICON],
    [undefined, DEFAULT_ICON],
    ["constructor", DEFAULT_ICON],
  ])("uses the icon for %s", (slug, icon) => {
    expect(disciplineIcon(slug)).toBe(icon);
  });

  it("names every workout type through the backend translations", () => {
    const workout = entity("on", {});
    for (const slug of SLUGS) {
      expect(disciplineName(hass, workout, slug)).toBe(WORKOUT_TYPE_NAMES[slug]);
    }
    expect(disciplineName(hass, workout, "caesar")).toBe("Rowing");
  });

  it("title-cases slugs without a translation", () => {
    const workout = entity("on", {});
    expect(disciplineName(hass, workout, "outdoor_running")).toBe("Outdoor running");
    expect(disciplineName({}, workout, "bike_bootcamp")).toBe("Bike bootcamp");
    expect(disciplineName(hass, undefined, "cycling")).toBe("Cycling");
    expect(disciplineName({ formatEntityAttributeValue: () => "" }, workout, "yoga")).toBe("Yoga");
    const throwing = {
      formatEntityAttributeValue: () => {
        throw new Error("boom");
      },
    };
    expect(disciplineName(throwing, workout, "foo_bar")).toBe("Foo bar");
  });

  it.each([
    ["foo_bar", "Foo bar"],
    ["cycling", "Cycling"],
    ["a", "A"],
    ["_", "_"],
    ["", ""],
  ])("title-cases %s as %s", (slug, text) => {
    expect(titleCase(slug)).toBe(text);
  });
});

describe("localize", () => {
  it("uses the language, then the base language, then English, then the key", () => {
    expect(localize({ language: "en" }, "chip.paused")).toBe("Paused");
    expect(localize({ locale: { language: "en-GB" } }, "chip.paused")).toBe("Paused");
    expect(localize({ language: "de" }, "chip.paused")).toBe("Paused");
    expect(localize(undefined, "chip.paused")).toBe("Paused");
    expect(localize(undefined, "no.such.key")).toBe("no.such.key");
  });

  it("prefers a regional string, then the base language", () => {
    const table = TRANSLATIONS as Record<string, Record<string, string>>;
    table.de = { "chip.paused": "Pausiert" };
    table["de-CH"] = { "chip.idle": "Letztes Training" };
    try {
      expect(localize({ language: "de-CH" }, "chip.idle")).toBe("Letztes Training");
      expect(localize({ language: "de-CH" }, "chip.paused")).toBe("Pausiert");
      expect(localize({ language: "de_AT" }, "chip.paused")).toBe("Pausiert");
      expect(localize({ language: "de" }, "chip.active")).toBe("In progress");
    } finally {
      delete table.de;
      delete table["de-CH"];
    }
  });

  it("replaces placeholders", () => {
    expect(localize(undefined, "leaderboard", { rank: 3, total: "10" })).toBe("Rank 3 of 10");
    expect(localize(undefined, "leaderboard", { rank: 3 })).toBe("Rank 3 of {total}");
  });

  it("reads the language from locale, else language", () => {
    expect(language({ locale: { language: "fr" }, language: "de" })).toBe("fr");
    expect(language({ locale: { language: "" }, language: "de" })).toBe("de");
    expect(language({ locale: null, language: 5 })).toBeUndefined();
    expect(language("en")).toBeUndefined();
  });

  it("keeps every string plain ASCII", () => {
    for (const [key, text] of Object.entries(TRANSLATIONS.en)) {
      expect(key).toMatch(/^[a-z_.]+$/);
      expect(text.replace("\u00b7", "")).toMatch(/^[\x20-\x7e]*$/);
      expect(text).not.toContain("!");
    }
  });
});
