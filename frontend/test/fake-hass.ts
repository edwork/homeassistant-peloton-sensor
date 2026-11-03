// A fake hass object for the card tests, shaped like the frontend's.
import strings from "../../custom_components/peloton/strings.json";
import { validateConfig } from "../src/config";
import type {
  CardConfig,
  DeviceRegistryEntry,
  EntityRegistryEntry,
  HassEntity,
  HomeAssistant,
  ValuePart,
} from "../src/types";

export const DEVICE_ID = "device-1";
export const PREFIX = "jane_on_peloton";

// Units of the integration's sensors (imperial account settings).
export const UNITS: Readonly<Record<string, string>> = {
  output: "W",
  cadence: "rpm",
  resistance: "%",
  heart_rate: "bpm",
  speed: "mph",
  pace: "min/mi",
  incline: "%",
  stroke_rate: "spm",
  split_pace: "min/500m",
  total_output: "kJ",
  total_work: "Wh",
  distance: "mi",
  total_calories: "kcal",
  active_calories: "kcal",
  duration: "min",
  elevation: "ft",
};

const METRICS = [
  "output",
  "cadence",
  "resistance",
  "heart_rate",
  "speed",
  "pace",
  "incline",
  "stroke_rate",
  "split_pace",
];

/** Translation keys of every entity the integration creates. */
export const ALL_KEYS: readonly string[] = [
  "workout",
  "start_time",
  "end_time",
  "duration",
  "leaderboard_rank",
  "leaderboard_total_users",
  "total_work",
  "distance",
  "total_calories",
  "active_calories",
  "total_output",
  "total_workouts",
  ...METRICS.flatMap((key) => [`${key}_average`, `${key}_max`, `${key}_current`]),
];

/** Backend state translations of workout_type, read from strings.json. */
export const WORKOUT_TYPE_NAMES: Readonly<Record<string, string>> =
  strings.entity.binary_sensor.workout.state_attributes.workout_type.state;

function unitOf(key: string): string | undefined {
  const metric = key.replace(/_(average|max|current)$/, "");
  return UNITS[metric];
}

export function entityIdOf(key: string, prefix = PREFIX): string {
  return key === "workout" ? `binary_sensor.${prefix}_workout` : `sensor.${prefix}_${key}`;
}

/** A state object for an integration entity, with its unit or device class. */
export function stateFor(
  entityId: string,
  key: string,
  state: string,
  extra: Record<string, unknown> = {},
): HassEntity {
  const attributes: Record<string, unknown> = {};
  const unit = unitOf(key);
  if (unit) attributes.unit_of_measurement = unit;
  if (key === "start_time" || key === "end_time") attributes.device_class = "timestamp";
  return { entity_id: entityId, state, attributes: { ...attributes, ...extra } };
}

/** The stub formatters: values and units as parts, timestamps as "at <iso>". */
export const formatters = {
  formatEntityStateToParts(stateObj: HassEntity): ValuePart[] {
    const unit = stateObj.attributes.unit_of_measurement;
    const parts: ValuePart[] = [{ type: "value", value: stateObj.state }];
    if (typeof unit === "string") {
      parts.push({ type: "literal", value: unit === "%" ? "" : " " });
      parts.push({ type: "unit", value: unit });
    }
    return parts;
  },
  formatEntityState(stateObj: HassEntity): string {
    if (stateObj.attributes.device_class === "timestamp") return `at ${stateObj.state}`;
    return formatters
      .formatEntityStateToParts(stateObj)
      .map((part) => part.value)
      .join("");
  },
  formatEntityAttributeValue(stateObj: HassEntity, attribute: string, value?: unknown): string {
    const raw = value ?? stateObj.attributes[attribute];
    if (attribute === "workout_type" && typeof raw === "string" && raw in WORKOUT_TYPE_NAMES) {
      return WORKOUT_TYPE_NAMES[raw];
    }
    return String(raw);
  },
};

export interface RiderOptions {
  deviceId?: string;
  name?: string;
  nameByUser?: string | null;
  disabled?: boolean;
  prefix?: string;
  /** Translation keys absent from hass.entities and hass.states (disabled). */
  disabledKeys?: readonly string[];
  /** Translation keys in hass.entities without a state (just enabled). */
  noState?: readonly string[];
  /** States by translation key; others are "unknown". */
  states?: Readonly<
    Record<string, string | { state: string; attributes?: Record<string, unknown> }>
  >;
  /** Attributes of the workout binary sensor. */
  workout?: Record<string, unknown>;
}

export interface Rider {
  device: DeviceRegistryEntry;
  entities: Record<string, EntityRegistryEntry>;
  states: Record<string, HassEntity>;
}

/** One Peloton device with all its entities. */
export function rider(options: RiderOptions = {}): Rider {
  const deviceId = options.deviceId ?? DEVICE_ID;
  const prefix = options.prefix ?? PREFIX;
  const device: DeviceRegistryEntry = {
    id: deviceId,
    identifiers: [["peloton", `user-${deviceId}`]],
    name: options.name ?? "Jane on Peloton",
    name_by_user: options.nameByUser ?? null,
    disabled_by: options.disabled ? "user" : null,
  };
  const entities: Record<string, EntityRegistryEntry> = {};
  const states: Record<string, HassEntity> = {};
  for (const key of ALL_KEYS) {
    if (options.disabledKeys?.includes(key)) continue;
    const entityId = entityIdOf(key, prefix);
    entities[entityId] = {
      entity_id: entityId,
      device_id: deviceId,
      platform: "peloton",
      translation_key: key,
    };
    if (options.noState?.includes(key)) continue;
    const given = options.states?.[key];
    const spec = typeof given === "string" ? { state: given } : given;
    const extra =
      key === "workout" ? { ...options.workout, ...spec?.attributes } : spec?.attributes;
    states[entityId] = stateFor(
      entityId,
      key,
      spec?.state ?? (key === "workout" ? "off" : "unknown"),
      extra,
    );
  }
  return { device, entities, states };
}

export interface HassOptions {
  riders?: readonly Rider[];
  /** Extra states, entities and devices, such as unrelated integrations. */
  states?: Record<string, HassEntity>;
  entities?: Record<string, EntityRegistryEntry>;
  devices?: Record<string, DeviceRegistryEntry>;
  language?: string;
  /** False leaves out the formatter functions (old or stale frontend). */
  withFormatters?: boolean;
}

export function makeHass(options: HassOptions = {}): HomeAssistant {
  const riders = options.riders ?? [rider()];
  const hass: HomeAssistant = {
    states: { ...options.states },
    entities: { ...options.entities },
    devices: { ...options.devices },
    language: options.language ?? "en",
    locale: { language: options.language ?? "en" },
    connected: true,
  };
  for (const item of riders) {
    Object.assign(hass.states, item.states);
    Object.assign(hass.entities as object, item.entities);
    (hass.devices as Record<string, DeviceRegistryEntry>)[item.device.id] = item.device;
  }
  if (options.withFormatters !== false) Object.assign(hass, formatters);
  return hass;
}

/** A hass for one rider; shorthand for makeHass({riders: [rider(options)]}). */
export function hassWith(options: RiderOptions = {}, extra: Omit<HassOptions, "riders"> = {}) {
  return makeHass({ ...extra, riders: [rider(options)] });
}

/** A validated config. */
export function config(raw: Record<string, unknown> = {}): CardConfig {
  return validateConfig({ type: "custom:peloton-workout-card", ...raw });
}

/** A contract fixture written by tests/test_card_fixtures.py. */
export interface Fixture {
  states: Record<string, { state: string; attributes: Record<string, unknown> }>;
  entities: Record<string, EntityRegistryEntry>;
  devices: Record<string, Omit<DeviceRegistryEntry, "id">>;
}

/** A hass from a contract fixture, with the stub formatters. */
export function hassFromFixture(fixture: Fixture): HomeAssistant {
  const states: Record<string, HassEntity> = {};
  for (const [entityId, value] of Object.entries(fixture.states)) {
    states[entityId] = {
      entity_id: entityId,
      state: value.state,
      attributes: value.attributes ?? {},
    };
  }
  // hass.devices entries carry their id; the fixtures key devices by id only.
  const devices: Record<string, DeviceRegistryEntry> = {};
  for (const [id, device] of Object.entries(fixture.devices)) devices[id] = { ...device, id };
  return {
    states,
    entities: fixture.entities,
    devices,
    language: "en",
    locale: { language: "en" },
    connected: true,
    ...formatters,
  };
}

/** A small deterministic random generator (mulberry32). */
export function seededRandom(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value = (value + 0x6d2b79f5) >>> 0;
    let t = value;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Vite's import.meta.glob, typed here because the tests do not load Vite's
// client types.
declare global {
  interface ImportMeta {
    glob<T>(
      pattern: string,
      options: { eager: true; import?: string; query?: string },
    ): Record<string, T>;
  }
}

// node:fs, loaded by name because the tests do not load Node's types.
const NODE_FS = "node:fs";
const fs = (await import(/* @vite-ignore */ NODE_FS)) as {
  readFileSync(path: URL, encoding: "utf8"): string;
};

/** A file of the repository, relative to this directory. */
export function repoFile(path: string): string {
  return fs.readFileSync(new URL(path, import.meta.url), "utf8");
}

/** The workout_type values offered by the blueprint's skip_workout_types select. */
export function blueprintWorkoutTypes(): string[] {
  const text = repoFile("../../blueprints/automation/peloton/workout_fan.yaml");
  return [...text.matchAll(/^\s*value: ([a-z_]+)\s*$/gm)].map((match) => match[1]);
}
