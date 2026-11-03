import { describe, expect, it } from "vitest";
import {
  attributes,
  entitySuggestion,
  known,
  pelotonDevices,
  resolve,
  stateObj,
  stubConfig,
} from "../src/resolve";
import type { HomeAssistant, Resolution } from "../src/types";
import { config, DEVICE_ID, entityIdOf, hassWith, makeHass, rider } from "./fake-hass";

function ok(resolution: Resolution) {
  if (resolution.status !== "ok") throw new Error(`expected ok, got ${resolution.status}`);
  return resolution;
}

const unrelatedDevice = {
  "other-device": {
    id: "other-device",
    identifiers: [["hue", "x"]] as [string, string][],
    name: "Lamp",
  },
};

describe("resolve", () => {
  it.each([
    ["no hass", undefined],
    ["null hass", null],
    ["null entities", { states: {}, entities: null, devices: {} }],
    ["null devices", { states: {}, entities: {}, devices: null }],
  ])("returns loading with %s", (_name, hass) => {
    expect(resolve(hass, config()).status).toBe("loading");
  });

  it("finds no device", () => {
    const hass = makeHass({ riders: [], devices: unrelatedDevice });
    expect(resolve(hass, config()).status).toBe("no_device");
  });

  it("uses the only device", () => {
    const result = ok(resolve(hassWith(), config()));
    expect(result.deviceId).toBe(DEVICE_ID);
    expect(result.name).toBe("Jane on Peloton");
    expect(result.map.workout).toBe(entityIdOf("workout"));
    expect(result.map.output_current).toBe(entityIdOf("output_current"));
  });

  it("names the rider from config, then name_by_user, then name", () => {
    expect(ok(resolve(hassWith({ nameByUser: "Bike" }), config())).name).toBe("Bike");
    expect(ok(resolve(hassWith({ nameByUser: "Bike" }), config({ name: "Jane" }))).name).toBe(
      "Jane",
    );
    expect(ok(resolve(hassWith({ name: "" }), config())).name).toBe("Peloton");
  });

  it("asks to choose between two enabled devices", () => {
    const hass = makeHass({
      riders: [rider(), rider({ deviceId: "device-2", name: "John", prefix: "john_on_peloton" })],
    });
    expect(resolve(hass, config()).status).toBe("choose_device");
  });

  it("uses the enabled device when the other is disabled", () => {
    const hass = makeHass({
      riders: [rider({ disabled: true }), rider({ deviceId: "device-2", name: "John" })],
    });
    expect(ok(resolve(hass, config())).deviceId).toBe("device-2");
  });

  it("reports no device when the only device is disabled", () => {
    expect(resolve(hassWith({ disabled: true }), config()).status).toBe("no_device");
  });

  it("reports a disabled or missing device_id", () => {
    expect(resolve(hassWith({ disabled: true }), config({ device_id: DEVICE_ID })).status).toBe(
      "device_disabled",
    );
    expect(resolve(hassWith(), config({ device_id: "gone" })).status).toBe("device_not_found");
    const hass = makeHass({ riders: [], devices: unrelatedDevice });
    expect(resolve(hass, config({ device_id: "other-device" })).status).toBe("device_not_found");
  });

  it("maps only the selected device's entities (_2 multi-account)", () => {
    const hass = makeHass({
      riders: [rider(), rider({ deviceId: "device-2", prefix: "jane_on_peloton_2" })],
    });
    const result = ok(resolve(hass, config({ device_id: "device-2" })));
    expect(result.map.workout).toBe("binary_sensor.jane_on_peloton_2_workout");
    expect(result.map.output_current).toBe("sensor.jane_on_peloton_2_output_current");
    expect(result.watched.every((id) => id.includes("_2_"))).toBe(true);
  });

  it("follows renamed and legacy entity ids through the registry", () => {
    const hass = hassWith();
    const entities = hass.entities as Record<string, { entity_id: string }>;
    const renamed = entities[entityIdOf("output_current")];
    delete entities[entityIdOf("output_current")];
    entities["sensor.my_bike_power"] = { ...renamed, entity_id: "sensor.my_bike_power" };
    const legacy = entities[entityIdOf("total_work")];
    delete entities[entityIdOf("total_work")];
    entities["sensor.jane_on_peloton_power_output"] = {
      ...legacy,
      entity_id: "sensor.jane_on_peloton_power_output",
    };
    const result = ok(resolve(hass, config()));
    expect(result.map.output_current).toBe("sensor.my_bike_power");
    expect(result.map.total_work).toBe("sensor.jane_on_peloton_power_output");
  });

  it("skips entities of other platforms, other devices and without translation key", () => {
    const hass = hassWith();
    Object.assign(hass.entities as object, {
      "sensor.foreign": {
        entity_id: "sensor.foreign",
        device_id: DEVICE_ID,
        platform: "template",
        translation_key: "output_current",
      },
      "sensor.no_key": { entity_id: "sensor.no_key", device_id: DEVICE_ID, platform: "peloton" },
      "sensor.empty_key": {
        entity_id: "sensor.empty_key",
        device_id: DEVICE_ID,
        platform: "peloton",
        translation_key: "",
      },
      broken: null,
    });
    const result = ok(resolve(hass, config()));
    expect(result.map.output_current).toBe(entityIdOf("output_current"));
    expect(Object.values(result.map)).not.toContain("sensor.no_key");
    expect(Object.keys(result.map)).not.toContain("");
  });

  it("leaves a disabled metric out of the map and watched list", () => {
    const result = ok(resolve(hassWith({ disabledKeys: ["cadence_current"] }), config()));
    expect(result.map.cadence_current).toBeUndefined();
    expect(result.map.cadence_average).toBeDefined();
    expect(result.watched).not.toContain(entityIdOf("cadence_current"));
  });

  it("reports a disabled workout sensor or a legacy entry without translation key", () => {
    expect(resolve(hassWith({ disabledKeys: ["workout"] }), config()).status).toBe(
      "workout_missing",
    );
    const hass = hassWith();
    const entry = (hass.entities as Record<string, { translation_key?: string }>)[
      entityIdOf("workout")
    ];
    delete entry.translation_key;
    expect(resolve(hass, config()).status).toBe("workout_missing");
  });

  it("applies entity overrides on top of the registry", () => {
    const hass = hassWith({ disabledKeys: ["workout"] });
    const result = ok(
      resolve(
        hass,
        config({
          entities: {
            workout: "binary_sensor.legacy_workout",
            output_current: "sensor.legacy_output",
          },
        }),
      ),
    );
    expect(result.map.workout).toBe("binary_sensor.legacy_workout");
    expect(result.map.output_current).toBe("sensor.legacy_output");
    expect(result.watched).toContain("sensor.legacy_output");
  });

  it("rejects overrides with a wrong domain or an unknown key", () => {
    expect(() => config({ entities: { workout: "sensor.x" } })).toThrow(/binary_sensor/);
    expect(() => config({ entities: { output_current: "binary_sensor.x" } })).toThrow(/sensor/);
    expect(() => config({ entities: { power: "sensor.x" } })).toThrow(/unknown key/);
  });

  it("works with legacy overrides and no registry entry at all", () => {
    const hass = makeHass({ riders: [rider({ disabledKeys: ["workout"] })] });
    const result = resolve(hass, config({ entities: { workout: "binary_sensor.old" } }));
    expect(ok(result).map.workout).toBe("binary_sensor.old");
  });

  it("memoizes on the registries and the config", () => {
    const hass = hassWith();
    const cfg = config();
    const first = resolve(hass, cfg);
    expect(resolve({ ...hass, states: {} }, cfg)).toBe(first);
    expect(resolve({ ...hass, entities: { ...hass.entities } }, cfg)).not.toBe(first);
    expect(resolve({ ...hass, devices: { ...hass.devices } }, cfg)).not.toBe(first);
    expect(resolve(hass, config())).not.toBe(first);
    expect(resolve(hass, config())).toEqual(first);
  });

  it("watches the header, metric, totals and leaderboard sensors", () => {
    const all = ok(resolve(hassWith(), config())).watched;
    for (const key of [
      "workout",
      "start_time",
      "end_time",
      "total_workouts",
      "split_pace_max",
      "total_output",
      "duration",
      "leaderboard_rank",
    ]) {
      expect(all).toContain(entityIdOf(key));
    }
    expect(all).not.toContain(entityIdOf("total_work"));
    expect(new Set(all).size).toBe(all.length);

    const narrow = ok(
      resolve(
        hassWith(),
        config({ metrics: ["cadence"], show_totals: false, show_leaderboard: false }),
      ),
    ).watched;
    expect(narrow).toContain(entityIdOf("cadence_max"));
    expect(narrow).not.toContain(entityIdOf("output_current"));
    expect(narrow).not.toContain(entityIdOf("total_calories"));
    expect(narrow).not.toContain(entityIdOf("leaderboard_rank"));
    // The pre-roll hint reads these whatever the config shows.
    expect(narrow).toContain(entityIdOf("output_average"));
    expect(narrow).toContain(entityIdOf("total_output"));
    expect(narrow).toContain(entityIdOf("distance"));
  });
});

describe("known and stateObj", () => {
  const hass = hassWith({
    states: { output_current: "120", cadence_current: "unavailable" },
    noState: ["resistance_current"],
  });
  const { map } = ok(resolve(hass, config()));

  it("is true only for a mapped entity with a value", () => {
    expect(known(hass, map, "output_current")).toBe(true);
    expect(known(hass, map, "cadence_current")).toBe(false);
    expect(known(hass, map, "heart_rate_current")).toBe(false);
    expect(known(hass, map, "resistance_current")).toBe(false);
    expect(known(hass, map, "not_a_key")).toBe(false);
    expect(known(hass, { x: "sensor.empty" }, "x")).toBe(false);
    expect(
      known(
        { states: { "sensor.empty": { entity_id: "sensor.empty", state: "", attributes: {} } } },
        { x: "sensor.empty" },
        "x",
      ),
    ).toBe(false);
  });

  it("ignores malformed states", () => {
    const broken = { states: { "sensor.a": { state: 5 }, "sensor.b": "on" } };
    expect(stateObj(broken, "sensor.a")).toBeUndefined();
    expect(stateObj(broken, "sensor.b")).toBeUndefined();
    expect(stateObj({ states: null }, "sensor.a")).toBeUndefined();
    expect(stateObj(hass, undefined)).toBeUndefined();
    expect(attributes({ entity_id: "x", state: "on", attributes: null as never })).toEqual({});
    expect(attributes(undefined)).toEqual({});
  });
});

describe("devices, stub config and entity suggestion", () => {
  it("sorts Peloton devices by display name", () => {
    const hass = makeHass({
      riders: [
        rider({ deviceId: "b", name: "Zed" }),
        rider({ deviceId: "a", name: "Amy" }),
        rider({ deviceId: "c", name: "Zed", nameByUser: "Bob" }),
        rider({ deviceId: "d", name: "Amy" }),
      ],
      devices: unrelatedDevice,
    });
    expect(pelotonDevices(hass).map((device) => device.id)).toEqual(["a", "d", "c", "b"]);
    expect(pelotonDevices({ devices: { x: { id: "x", identifiers: "peloton" } } })).toEqual([]);
    expect(pelotonDevices(null)).toEqual([]);
  });

  it("stubs the only enabled device", () => {
    expect(stubConfig(makeHass({ riders: [] }))).toEqual({ variant: "full" });
    expect(stubConfig(hassWith())).toEqual({ variant: "full", device_id: DEVICE_ID });
    expect(
      stubConfig(makeHass({ riders: [rider(), rider({ deviceId: "device-2", disabled: true })] })),
    ).toEqual({ variant: "full", device_id: DEVICE_ID });
    expect(stubConfig(makeHass({ riders: [rider(), rider({ deviceId: "device-2" })] }))).toEqual({
      variant: "full",
    });
    expect(stubConfig({ ...hassWith(), devices: null })).toEqual({ variant: "full" });
    expect(stubConfig(undefined)).toEqual({ variant: "full" });
    const throwing = {
      get devices(): never {
        throw new Error("boom");
      },
    };
    expect(stubConfig(throwing)).toEqual({ variant: "full" });
  });

  it("suggests a card for a Peloton workout sensor only", () => {
    const hass = hassWith();
    expect(entitySuggestion(hass, entityIdOf("workout"))).toEqual({
      config: { type: "custom:peloton-workout-card", device_id: DEVICE_ID },
    });
    expect(entitySuggestion(hass, entityIdOf("output_current"))).toBeNull();
    expect(entitySuggestion(hass, "light.unknown")).toBeNull();
    expect(entitySuggestion({ ...hass, entities: null } as HomeAssistant, "x")).toBeNull();
    expect(entitySuggestion(hass, 5)).toBeNull();
  });
});
