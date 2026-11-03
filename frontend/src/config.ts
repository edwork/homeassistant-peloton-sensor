// Card configuration: defaults, validation and the editor form.
import { localize } from "./localize";
import { type CardConfig, METRIC_KEYS, type MetricKey, type Variant } from "./types";

export type { CardConfig } from "./types";
export { METRIC_KEYS } from "./types";

// Replaced at build time (esbuild --define); "dev" in tests and local builds.
declare const __PELOTON_CARDS_VERSION__: string;
export const CARD_VERSION: string =
  typeof __PELOTON_CARDS_VERSION__ === "string" ? __PELOTON_CARDS_VERSION__ : "dev";

export const CARD_TYPE = "peloton-workout-card";

export const VARIANTS: readonly Variant[] = ["full", "compact"];

export const DEFAULTS: CardConfig = Object.freeze({
  type: `custom:${CARD_TYPE}`,
  variant: "full",
  metrics: Object.freeze([]),
  show_image: true,
  show_totals: true,
  show_leaderboard: true,
  entities: Object.freeze({}),
});

const BOOLEAN_KEYS = ["show_image", "show_totals", "show_leaderboard"] as const;

/** Translation keys of the integration's entities, which `entities` may override. */
export const ENTITY_KEYS: readonly string[] = [
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
  "stroke_count",
  "elevation",
  ...METRIC_KEYS.flatMap((key) => [`${key}_average`, `${key}_max`, `${key}_current`]),
  "bike_bootcamp_count",
  "rowing_count",
  "row_bootcamp_count",
  "cardio_count",
  "tread_bootcamp_count",
  "cycling_count",
  "meditation_count",
  "running_count",
  "strength_count",
  "stretching_count",
  "walking_count",
  "yoga_count",
];

const OBJECT_ID = /^[a-z0-9_]+$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** True for values a cleared form field leaves behind. */
function isCleared(value: unknown): boolean {
  return value === undefined || value === null || value === "";
}

function optionalString(raw: Record<string, unknown>, key: string): string | undefined {
  const value = raw[key];
  if (isCleared(value)) return undefined;
  if (typeof value !== "string") throw new Error(`${key} must be a string.`);
  return value.trim() === "" ? undefined : value;
}

function validateMetrics(value: unknown): readonly MetricKey[] {
  if (isCleared(value)) return DEFAULTS.metrics;
  if (!Array.isArray(value)) throw new Error("metrics must be a list of metric keys.");
  const seen = new Set<string>();
  for (const key of value) {
    if (typeof key !== "string" || !(METRIC_KEYS as readonly string[]).includes(key)) {
      throw new Error(
        `metrics contains an unknown key: ${String(key)}. Known keys: ${METRIC_KEYS.join(", ")}.`,
      );
    }
    if (seen.has(key)) throw new Error(`metrics lists ${key} more than once.`);
    seen.add(key);
  }
  return Object.freeze([...value] as MetricKey[]);
}

function validateEntities(value: unknown): Readonly<Record<string, string>> {
  if (isCleared(value)) return DEFAULTS.entities;
  if (!isRecord(value)) {
    throw new Error("entities must be a map of translation keys to entity ids.");
  }
  const result: Record<string, string> = {};
  for (const [key, entityId] of Object.entries(value)) {
    if (!ENTITY_KEYS.includes(key)) throw new Error(`entities has an unknown key: ${key}.`);
    if (isCleared(entityId)) continue;
    if (typeof entityId !== "string") throw new Error(`entities.${key} must be an entity id.`);
    const domain = key === "workout" ? "binary_sensor" : "sensor";
    const [prefix, objectId, ...rest] = entityId.split(".");
    if (prefix !== domain || objectId === undefined || rest.length || !OBJECT_ID.test(objectId)) {
      throw new Error(`entities.${key} must be a ${domain} entity id, such as ${domain}.example.`);
    }
    result[key] = entityId;
  }
  return Object.freeze(result);
}

/**
 * Validate a raw card configuration and return a new frozen config with the
 * defaults applied. The input is never changed (the editor deep-freezes it).
 * Unknown top-level keys, such as grid_options or visibility, are ignored.
 * Throws an Error with a plain message for an invalid value.
 */
export function validateConfig(raw: unknown): CardConfig {
  if (!isRecord(raw)) throw new Error("The card configuration must be an object.");

  const variant = isCleared(raw.variant) ? DEFAULTS.variant : raw.variant;
  if (typeof variant !== "string" || !(VARIANTS as readonly string[]).includes(variant)) {
    throw new Error(`variant must be one of: ${VARIANTS.join(", ")}.`);
  }

  const booleans: Record<string, boolean> = {};
  for (const key of BOOLEAN_KEYS) {
    const value = raw[key];
    if (isCleared(value)) booleans[key] = DEFAULTS[key];
    else if (typeof value === "boolean") booleans[key] = value;
    else throw new Error(`${key} must be true or false.`);
  }

  let tapAction: CardConfig["tap_action"];
  if (!isCleared(raw.tap_action)) {
    if (!isRecord(raw.tap_action)) throw new Error("tap_action must be an action object.");
    tapAction = raw.tap_action;
  }

  // Unset optional keys are left out, so the object reads like the YAML.
  const deviceId = optionalString(raw, "device_id");
  const name = optionalString(raw, "name");
  return Object.freeze({
    type: typeof raw.type === "string" ? raw.type : DEFAULTS.type,
    ...(deviceId !== undefined && { device_id: deviceId }),
    ...(name !== undefined && { name }),
    variant: variant as Variant,
    metrics: validateMetrics(raw.metrics),
    show_image: booleans.show_image,
    show_totals: booleans.show_totals,
    show_leaderboard: booleans.show_leaderboard,
    ...(tapAction !== undefined && { tap_action: tapAction }),
    entities: validateEntities(raw.entities),
  });
}

/** An ha-form schema item, as far as the card uses it. */
export interface FormSchema {
  readonly name: string;
  readonly type?: "expandable";
  readonly flatten?: boolean;
  readonly selector?: Readonly<Record<string, unknown>>;
  readonly schema?: readonly FormSchema[];
}

export const FORM_SCHEMA: readonly FormSchema[] = [
  { name: "device_id", selector: { device: { filter: { integration: "peloton" } } } },
  { name: "name", selector: { text: {} } },
  {
    name: "variant",
    selector: {
      select: {
        mode: "box",
        options: VARIANTS.map((value) => ({
          value,
          label: localize(undefined, `editor.variant_${value}`),
        })),
      },
    },
  },
  {
    name: "metrics",
    selector: {
      select: {
        multiple: true,
        reorder: true,
        options: METRIC_KEYS.map((value) => ({
          value,
          label: localize(undefined, `metric.${value}`),
        })),
      },
    },
  },
  {
    name: "content",
    type: "expandable",
    flatten: true,
    schema: BOOLEAN_KEYS.map((name) => ({ name, selector: { boolean: {} } })),
  },
  { name: "tap_action", selector: { ui_action: {} } },
];

const HELPERS: Readonly<Record<string, () => string>> = {
  device_id: () => localize(undefined, "editor.device_id_helper", { version: CARD_VERSION }),
  metrics: () => localize(undefined, "editor.metrics_helper"),
};

/** Label of a form field, from the card's own strings. */
export function computeLabel(schema: { name: string }): string {
  return localize(undefined, `editor.${schema.name}`);
}

/** Helper text of a form field, or undefined. */
export function computeHelper(schema: { name: string }): string | undefined {
  return Object.hasOwn(HELPERS, schema.name) ? HELPERS[schema.name]() : undefined;
}

/** The value of the card's static getConfigForm(). */
export function getConfigForm(): {
  schema: readonly FormSchema[];
  computeLabel: typeof computeLabel;
  computeHelper: typeof computeHelper;
  assertConfig: (config: unknown) => void;
} {
  return {
    schema: FORM_SCHEMA,
    computeLabel,
    computeHelper,
    assertConfig: (config: unknown) => {
      validateConfig(config);
    },
  };
}
