// Entity discovery through the device and entity registries.
import {
  type CardConfig,
  type DeviceRegistryEntry,
  type HassEntity,
  METRIC_KEYS,
  type Resolution,
} from "./types";

export const DOMAIN = "peloton";

/** Translation keys shown outside the tiles, in the order they are watched. */
export const TOTAL_KEYS = ["total_output", "distance", "total_calories", "duration"] as const;
export const LEADERBOARD_KEYS = ["leaderboard_rank", "leaderboard_total_users"] as const;
const HEADER_KEYS = ["workout", "start_time", "end_time", "total_workouts"] as const;

const LOADING: Resolution = Object.freeze({ status: "loading" });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/** Display name of a device: name_by_user, else name. */
export function deviceName(device: DeviceRegistryEntry): string | undefined {
  return str(device.name_by_user) ?? str(device.name);
}

function isPelotonDevice(device: unknown): device is DeviceRegistryEntry {
  if (!isRecord(device) || typeof device.id !== "string") return false;
  const { identifiers } = device;
  return (
    Array.isArray(identifiers) &&
    identifiers.some((pair) => Array.isArray(pair) && pair[0] === DOMAIN)
  );
}

/** Peloton devices in the device registry, sorted by display name. */
export function pelotonDevices(hass: unknown): DeviceRegistryEntry[] {
  if (!isRecord(hass) || !isRecord(hass.devices)) return [];
  return Object.values(hass.devices)
    .filter(isPelotonDevice)
    .sort((a, b) => {
      const left = deviceName(a) ?? "";
      const right = deviceName(b) ?? "";
      return left < right ? -1 : left > right ? 1 : 0;
    });
}

function isEnabled(device: DeviceRegistryEntry): boolean {
  return device.disabled_by === undefined || device.disabled_by === null;
}

/** getStubConfig: the device when exactly one enabled Peloton device exists. */
export function stubConfig(hass: unknown): { device_id?: string } {
  try {
    const enabled = pelotonDevices(hass).filter(isEnabled);
    return enabled.length === 1 ? { device_id: enabled[0].id } : {};
  } catch {
    return {};
  }
}

/** getEntitySuggestion: a card for the device of a Peloton workout sensor. */
export function entitySuggestion(
  hass: unknown,
  entityId: unknown,
): { config: { type: string; device_id: string } } | null {
  if (!isRecord(hass) || !isRecord(hass.entities) || typeof entityId !== "string") return null;
  const entry = Object.hasOwn(hass.entities, entityId) ? hass.entities[entityId] : undefined;
  if (
    !isRecord(entry) ||
    entry.platform !== DOMAIN ||
    entry.translation_key !== "workout" ||
    typeof entry.device_id !== "string"
  ) {
    return null;
  }
  return { config: { type: "custom:peloton-workout-card", device_id: entry.device_id } };
}

function pickDevice(
  devices: DeviceRegistryEntry[],
  deviceId: string | undefined,
): DeviceRegistryEntry | Resolution {
  if (deviceId !== undefined) {
    const device = devices.find((item) => item.id === deviceId);
    if (!device) return { status: "device_not_found" };
    return isEnabled(device) ? device : { status: "device_disabled" };
  }
  const enabled = devices.filter(isEnabled);
  if (enabled.length === 0) return { status: "no_device" };
  if (enabled.length > 1) return { status: "choose_device" };
  return enabled[0];
}

/** Entity ids the config can render, for shouldUpdate. */
function watchedIds(map: Readonly<Record<string, string>>, config: CardConfig): string[] {
  const metrics = config.metrics.length ? config.metrics : METRIC_KEYS;
  const keys: string[] = [
    ...HEADER_KEYS,
    ...metrics.flatMap((key) => [`${key}_current`, `${key}_average`, `${key}_max`]),
    ...(config.show_totals ? TOTAL_KEYS : []),
    ...(config.show_leaderboard ? LEADERBOARD_KEYS : []),
    // The inputs of sampleSignal in view.ts, whatever the config shows.
    ...METRIC_KEYS.map((key) => `${key}_average`),
    "total_output",
    "distance",
  ];
  const ids = keys.filter((key) => Object.hasOwn(map, key)).map((key) => map[key]);
  return [...new Set(ids)];
}

function compute(
  entities: Record<string, unknown>,
  devices: DeviceRegistryEntry[],
  config: CardConfig,
): Resolution {
  const picked = pickDevice(devices, config.device_id);
  if ("status" in picked) return Object.freeze(picked);
  const device = picked;

  const map: Record<string, string> = {};
  for (const entry of Object.values(entities)) {
    if (
      isRecord(entry) &&
      entry.platform === DOMAIN &&
      entry.device_id === device.id &&
      typeof entry.entity_id === "string" &&
      typeof entry.translation_key === "string" &&
      entry.translation_key !== ""
    ) {
      map[entry.translation_key] = entry.entity_id;
    }
  }
  const overrides = isRecord(config.entities) ? config.entities : {};
  for (const [key, entityId] of Object.entries(overrides)) {
    if (typeof entityId === "string") map[key] = entityId;
  }
  if (!Object.hasOwn(map, "workout")) return Object.freeze({ status: "workout_missing" });

  return Object.freeze({
    status: "ok",
    deviceId: device.id,
    name: str(config.name) ?? deviceName(device) ?? "Peloton",
    map: Object.freeze(map),
    watched: Object.freeze(watchedIds(map, config)),
  });
}

interface MemoEntry {
  entities: unknown;
  devices: unknown;
  result: Resolution;
}

// One entry per config object. The registries are replaced on every change,
// so their identities are enough to tell whether the entry is still valid.
const memo = new WeakMap<object, MemoEntry>();

/**
 * Find the device and entities the card shows. Pure and total: returns
 * "loading" until hass and both registries are there, and a problem status
 * when no single enabled device or no workout sensor is found.
 */
export function resolve(hass: unknown, config: CardConfig): Resolution {
  if (!isRecord(hass) || !isRecord(hass.entities) || !isRecord(hass.devices)) return LOADING;
  const { entities, devices } = hass;
  const cached = isRecord(config) ? memo.get(config) : undefined;
  if (cached && cached.entities === entities && cached.devices === devices) return cached.result;
  const result = compute(entities, pelotonDevices(hass), config);
  if (isRecord(config)) memo.set(config, { entities, devices, result });
  return result;
}

/** The state object of an entity id, or undefined when it has no usable state. */
export function stateObj(hass: unknown, entityId: string | undefined): HassEntity | undefined {
  if (entityId === undefined || !isRecord(hass) || !isRecord(hass.states)) return undefined;
  const value = Object.hasOwn(hass.states, entityId) ? hass.states[entityId] : undefined;
  if (!isRecord(value) || typeof value.state !== "string") return undefined;
  return value as unknown as HassEntity;
}

/** The attributes of a state object, or an empty object. */
export function attributes(state: HassEntity | undefined): Record<string, unknown> {
  return state && isRecord(state.attributes) ? state.attributes : {};
}

/** True when the state is a value: neither unknown nor unavailable. */
export function isKnownState(state: HassEntity | undefined): state is HassEntity {
  return (
    state !== undefined &&
    state.state !== "" &&
    state.state !== "unknown" &&
    state.state !== "unavailable"
  );
}

/** True when `key` is mapped and its entity has a known state. */
export function known(hass: unknown, map: Readonly<Record<string, string>>, key: string): boolean {
  return isKnownState(stateObj(hass, Object.hasOwn(map, key) ? map[key] : undefined));
}
