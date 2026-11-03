import { describe, expect, it } from "vitest";
import {
  CARD_VERSION,
  computeHelper,
  computeLabel,
  DEFAULTS,
  ENTITY_KEYS,
  FORM_SCHEMA,
  getConfigForm,
  METRIC_KEYS,
  validateConfig,
} from "../src/config";
import { ALL_KEYS } from "./fake-hass";

const TYPE = "custom:peloton-workout-card";

function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null) {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}

describe("validateConfig", () => {
  it("applies the defaults", () => {
    expect(validateConfig({ type: TYPE })).toEqual({
      type: TYPE,
      variant: "full",
      metrics: [],
      show_image: true,
      show_totals: true,
      show_leaderboard: true,
      entities: {},
    });
    expect(validateConfig({}).type).toBe(TYPE);
    expect(DEFAULTS.variant).toBe("full");
  });

  it("keeps valid values", () => {
    const tap = { action: "navigate", navigation_path: "/peloton" };
    const result = validateConfig({
      type: TYPE,
      device_id: "abc",
      name: "Jane",
      variant: "compact",
      metrics: ["heart_rate", "output"],
      show_image: false,
      show_totals: false,
      show_leaderboard: false,
      tap_action: tap,
      entities: { workout: "binary_sensor.jane_workout", output_current: "sensor.jane_output" },
    });
    expect(result).toEqual({
      type: TYPE,
      device_id: "abc",
      name: "Jane",
      variant: "compact",
      metrics: ["heart_rate", "output"],
      show_image: false,
      show_totals: false,
      show_leaderboard: false,
      tap_action: tap,
      entities: { workout: "binary_sensor.jane_workout", output_current: "sensor.jane_output" },
    });
  });

  it("normalizes cleared form values to the defaults", () => {
    const result = validateConfig({
      type: TYPE,
      device_id: "",
      name: "   ",
      variant: null,
      metrics: null,
      show_image: null,
      show_totals: undefined,
      show_leaderboard: "",
      tap_action: null,
      entities: null,
    });
    expect(result).toEqual(validateConfig({ type: TYPE }));
    expect("device_id" in result).toBe(false);
    expect("name" in result).toBe(false);
    expect("tap_action" in result).toBe(false);
    expect(
      validateConfig({ entities: { output_current: "", cadence_current: null } }).entities,
    ).toEqual({});
  });

  it("ignores unknown top-level keys", () => {
    const result = validateConfig({
      type: TYPE,
      grid_options: { columns: 6 },
      visibility: [{ condition: "state" }],
      view_layout: { position: "main" },
    });
    expect(result).not.toHaveProperty("grid_options");
    expect(result.variant).toBe("full");
  });

  it("returns a new frozen object and does not change a frozen input", () => {
    const raw = deepFreeze({
      type: TYPE,
      metrics: ["output"],
      entities: { output_current: "sensor.x" },
      tap_action: { action: "more-info" },
    });
    const copy = structuredClone(raw);
    const result = validateConfig(raw);
    expect(raw).toEqual(copy);
    expect(result).not.toBe(raw);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.metrics)).toBe(true);
    expect(Object.isFrozen(result.entities)).toBe(true);
    expect(result.metrics).not.toBe(raw.metrics);
  });

  it.each([
    ["not an object", null, /must be an object/],
    ["a list", [], /must be an object/],
    ["a string", "full", /must be an object/],
    ["device_id not a string", { device_id: 5 }, /device_id must be a string/],
    ["name not a string", { name: ["Jane"] }, /name must be a string/],
    ["unknown variant", { variant: "large" }, /variant must be one of: full, compact/],
    ["variant not a string", { variant: 1 }, /variant/],
    ["metrics not a list", { metrics: "output" }, /metrics must be a list/],
    ["unknown metric", { metrics: ["output", "power"] }, /unknown key: power/],
    ["metric not a string", { metrics: [1] }, /unknown key: 1/],
    ["duplicate metric", { metrics: ["output", "output"] }, /more than once/],
    ["show_image not a boolean", { show_image: "yes" }, /show_image must be true or false/],
    ["show_totals not a boolean", { show_totals: 1 }, /show_totals/],
    ["show_leaderboard not a boolean", { show_leaderboard: "false" }, /show_leaderboard/],
    ["tap_action not an object", { tap_action: "more-info" }, /tap_action must be/],
    ["tap_action a list", { tap_action: [] }, /tap_action must be/],
    ["entities not a map", { entities: ["sensor.x"] }, /entities must be a map/],
    ["entities a string", { entities: "sensor.x" }, /entities must be a map/],
    ["entity id not a string", { entities: { output_current: 5 } }, /must be an entity id/],
    ["workout not a binary sensor", { entities: { workout: "sensor.x" } }, /binary_sensor entity/],
    ["metric not a sensor", { entities: { output_current: "binary_sensor.x" } }, /a sensor entity/],
    ["entity id without object id", { entities: { output_current: "sensor." } }, /sensor entity/],
    ["entity id with two dots", { entities: { output_current: "sensor.a.b" } }, /sensor entity/],
    ["entity id with capitals", { entities: { output_current: "sensor.Output" } }, /sensor entity/],
    ["unknown translation key", { entities: { power_output: "sensor.x" } }, /unknown key/],
  ])("throws for %s", (_name, raw, message) => {
    expect(() => validateConfig(raw)).toThrow(message);
  });

  it("accepts every integration translation key in entities", () => {
    const counts = [
      "bike_bootcamp",
      "rowing",
      "row_bootcamp",
      "cardio",
      "tread_bootcamp",
      "cycling",
      "meditation",
      "running",
      "strength",
      "stretching",
      "walking",
      "yoga",
    ].map((name) => `${name}_count`);
    expect([...ENTITY_KEYS].sort()).toEqual(
      [...ALL_KEYS, "stroke_count", "elevation", ...counts].sort(),
    );
    for (const key of ENTITY_KEYS) {
      const domain = key === "workout" ? "binary_sensor" : "sensor";
      expect(validateConfig({ entities: { [key]: `${domain}.x` } }).entities[key]).toBe(
        `${domain}.x`,
      );
    }
  });
});

describe("getConfigForm", () => {
  it("has the schema of the design", () => {
    expect(FORM_SCHEMA.map((item) => item.name)).toEqual([
      "device_id",
      "name",
      "variant",
      "metrics",
      "content",
      "tap_action",
    ]);
    expect(FORM_SCHEMA[0].selector).toEqual({ device: { filter: { integration: "peloton" } } });
    expect(FORM_SCHEMA[2].selector).toEqual({
      select: {
        mode: "box",
        options: [
          { value: "full", label: "Full" },
          { value: "compact", label: "Compact" },
        ],
      },
    });
    const metrics = FORM_SCHEMA[3].selector?.select as {
      multiple: boolean;
      reorder: boolean;
      options: { value: string; label: string }[];
    };
    expect(metrics.multiple).toBe(true);
    expect(metrics.reorder).toBe(true);
    expect(metrics.options.map((option) => option.value)).toEqual([...METRIC_KEYS]);
    expect(metrics.options.find((option) => option.value === "heart_rate")?.label).toBe(
      "Heart rate",
    );
    const content = FORM_SCHEMA[4];
    expect(content.type).toBe("expandable");
    expect(content.flatten).toBe(true);
    expect(content.schema).toEqual([
      { name: "show_image", selector: { boolean: {} } },
      { name: "show_totals", selector: { boolean: {} } },
      { name: "show_leaderboard", selector: { boolean: {} } },
    ]);
    expect(FORM_SCHEMA[5].selector).toEqual({ ui_action: {} });
  });

  it("labels every field", () => {
    const names = FORM_SCHEMA.flatMap((item) => [item, ...(item.schema ?? [])]).map(
      (item) => item.name,
    );
    for (const name of names) {
      expect(computeLabel({ name })).not.toMatch(/^editor\./);
    }
    expect(computeLabel({ name: "content" })).toBe("Content");
  });

  it("explains metrics and shows the card version", () => {
    expect(computeHelper({ name: "metrics" })).toBe(
      "Leave empty to choose by workout type. Disabled sensors are skipped.",
    );
    expect(CARD_VERSION).toBe("dev");
    expect(computeHelper({ name: "device_id" })).toBe("Card version dev");
    expect(computeHelper({ name: "name" })).toBeUndefined();
  });

  it("asserts the config with validateConfig", () => {
    const form = getConfigForm();
    expect(form.schema).toBe(FORM_SCHEMA);
    expect(form.computeLabel).toBe(computeLabel);
    expect(form.computeHelper).toBe(computeHelper);
    expect(() => form.assertConfig({ type: TYPE })).not.toThrow();
    expect(() => form.assertConfig({ type: TYPE, variant: "large" })).toThrow(/variant/);
  });
});
