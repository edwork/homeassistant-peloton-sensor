// Value formatting, pace, discipline names and icons, metric sets.
import { language, localize } from "./localize";
import { attributes, isKnownState } from "./resolve";
import type { HassEntity, HomeAssistant, MetricKey, ValuePart, ValueView } from "./types";

/** Shown for unknown values (an em dash). */
export const DASH = "\u2014";

const PART_TYPES = new Set(["value", "literal", "unit"]);

// Units Home Assistant writes without a space before them.
const NO_SPACE_UNITS = new Set(["%", "\u00b0", "\u00b0C", "\u00b0F"]);

// Pace units in decimal minutes, shown as m:ss followed by the distance.
const PACE_UNITS: Readonly<Record<string, string>> = {
  "min/500m": "/500m",
  "min/mi": "/mi",
  "min/km": "/km",
};

const PACE_METRICS: ReadonlySet<string> = new Set(["pace", "split_pace"]);

type Formatters = Pick<
  HomeAssistant,
  "formatEntityState" | "formatEntityStateToParts" | "formatEntityAttributeValue"
>;

function formatters(hass: unknown): Formatters {
  return typeof hass === "object" && hass !== null ? (hass as Formatters) : {};
}

function view(parts: ValuePart[], hass: unknown): ValueView {
  const text = parts.map((part) => part.value).join("");
  if (text.trim() === "") return unknownValue(hass);
  return { parts, text, known: true, label: text };
}

/** The value view for an unknown value: a dash labelled "No value". */
export function unknownValue(hass: unknown): ValueView {
  return {
    parts: [{ type: "value", value: DASH }],
    text: DASH,
    known: false,
    label: localize(hass, "value.none"),
  };
}

function isParts(value: unknown): value is ValuePart[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (part) =>
        typeof part === "object" &&
        part !== null &&
        PART_TYPES.has((part as ValuePart).type) &&
        typeof (part as ValuePart).value === "string",
    )
  );
}

function unitParts(unit: unknown): ValuePart[] {
  if (typeof unit !== "string" || unit === "") return [];
  return [
    { type: "literal", value: NO_SPACE_UNITS.has(unit) ? "" : " " },
    { type: "unit", value: unit },
  ];
}

/** True for the metrics whose values are paces (decimal minutes). */
export function isPaceMetric(key: string): boolean {
  return PACE_METRICS.has(key);
}

/**
 * Format decimal minutes as m:ss, rounding to whole seconds with carry
 * (3.999 is 4:00). Returns null for values that are not finite or are 0 or
 * below.
 */
export function paceText(value: unknown): string | null {
  const minutes = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  if (typeof minutes !== "number" || !Number.isFinite(minutes) || minutes <= 0) return null;
  const seconds = Math.round(minutes * 60);
  if (seconds <= 0) return null;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Pace value parts: "4:05" and "/500m", "/mi" or "/km"; other units as given. */
export function paceParts(value: unknown, unit: unknown): ValuePart[] | null {
  const text = paceText(value);
  if (text === null) return null;
  const parts: ValuePart[] = [{ type: "value", value: text }];
  if (typeof unit === "string" && Object.hasOwn(PACE_UNITS, unit)) {
    parts.push({ type: "unit", value: PACE_UNITS[unit] });
  } else {
    parts.push(...unitParts(unit));
  }
  return parts;
}

/**
 * Format a sensor state for display. Uses hass.formatEntityStateToParts
 * (unit, display precision and locale), else the state and its unit. Paces
 * are formatted by the card as m:ss.
 */
export function formatValue(
  hass: unknown,
  state: HassEntity | undefined,
  options: { pace?: boolean } = {},
): ValueView {
  if (!isKnownState(state)) return unknownValue(hass);
  const unit = attributes(state).unit_of_measurement;
  if (options.pace) {
    const parts = paceParts(state.state, unit);
    return parts ? view(parts, hass) : unknownValue(hass);
  }
  const { formatEntityStateToParts } = formatters(hass);
  if (typeof formatEntityStateToParts === "function") {
    try {
      const parts: unknown = formatEntityStateToParts.call(hass, state);
      if (isParts(parts))
        return view(
          parts.map((part) => ({ ...part })),
          hass,
        );
    } catch {
      // Fall back to the raw state below.
    }
  }
  return view([{ type: "value", value: state.state }, ...unitParts(unit)], hass);
}

/** Format a whole state as text (timestamps, counts), or null when unknown. */
export function formatStateText(hass: unknown, state: HassEntity | undefined): string | null {
  if (!isKnownState(state)) return null;
  const { formatEntityState } = formatters(hass);
  if (typeof formatEntityState === "function") {
    try {
      const text: unknown = formatEntityState.call(hass, state);
      if (typeof text === "string" && text.trim() !== "") return text;
    } catch {
      // Fall back below.
    }
  }
  if (attributes(state).device_class === "timestamp") {
    const date = new Date(state.state);
    if (!Number.isNaN(date.getTime())) {
      try {
        return new Intl.DateTimeFormat(language(hass), {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(date);
      } catch {
        return date.toISOString();
      }
    }
  }
  return state.state;
}

/** "foo_bar" becomes "Foo bar". */
export function titleCase(slug: string): string {
  const words = slug.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : slug;
}

/**
 * Display name of a workout type. Uses the backend's state translation
 * through hass.formatEntityAttributeValue; when that returns the raw slug
 * (a stale frontend, or a slug new to Peloton) the slug is title-cased.
 */
export function disciplineName(
  hass: unknown,
  workout: HassEntity | undefined,
  slug: string,
): string {
  const { formatEntityAttributeValue } = formatters(hass);
  if (workout && typeof formatEntityAttributeValue === "function") {
    try {
      const name: unknown = formatEntityAttributeValue.call(hass, workout, "workout_type", slug);
      if (typeof name === "string" && name.trim() !== "" && name !== slug) return name;
    } catch {
      // Fall back below.
    }
  }
  return titleCase(slug);
}

const ICONS: Readonly<Record<string, string>> = {
  cycling: "mdi:bike",
  bike_bootcamp: "mdi:bike",
  running: "mdi:run",
  walking: "mdi:walk",
  caesar: "mdi:rowing",
  caesar_bootcamp: "mdi:rowing",
  circuit: "mdi:run-fast",
  strength: "mdi:dumbbell",
  yoga: "mdi:yoga",
  meditation: "mdi:meditation",
  stretching: "mdi:human-handsup",
  cardio: "mdi:heart-pulse",
};

export const DEFAULT_ICON = "mdi:bike";
export const WARNING_ICON = "mdi:alert-circle-outline";

/** Icon of a workout type; mdi:bike for unknown types. */
export function disciplineIcon(slug: unknown): string {
  return typeof slug === "string" && Object.hasOwn(ICONS, slug) ? ICONS[slug] : DEFAULT_ICON;
}

const BIKE_METRICS: readonly MetricKey[] = ["output", "cadence", "resistance", "heart_rate"];
const TREAD_METRICS: readonly MetricKey[] = ["speed", "pace", "incline", "heart_rate"];
const ROW_METRICS: readonly MetricKey[] = ["output", "stroke_rate", "split_pace", "heart_rate"];
const HEART_RATE_ONLY: readonly MetricKey[] = ["heart_rate"];

const AUTO_METRICS: Readonly<Record<string, readonly MetricKey[]>> = {
  cycling: BIKE_METRICS,
  bike_bootcamp: BIKE_METRICS,
  running: TREAD_METRICS,
  walking: TREAD_METRICS,
  circuit: TREAD_METRICS,
  caesar: ROW_METRICS,
  caesar_bootcamp: ROW_METRICS,
  strength: HEART_RATE_ONLY,
  yoga: HEART_RATE_ONLY,
  meditation: HEART_RATE_ONLY,
  stretching: HEART_RATE_ONLY,
  cardio: HEART_RATE_ONLY,
};

/** The automatic metrics of a workout type; bike metrics for unknown types. */
export function autoMetrics(slug: unknown): readonly MetricKey[] {
  return typeof slug === "string" && Object.hasOwn(AUTO_METRICS, slug)
    ? AUTO_METRICS[slug]
    : BIKE_METRICS;
}

const METRIC_DISCIPLINES: ReadonlySet<string> = new Set([
  "cycling",
  "bike_bootcamp",
  "running",
  "walking",
  "circuit",
  "caesar",
  "caesar_bootcamp",
]);

/** True for workout types whose equipment reports metrics. */
export function metricDiscipline(slug: unknown): boolean {
  return typeof slug === "string" && METRIC_DISCIPLINES.has(slug);
}

/** "Rank R of T", or null unless both states are known. */
export function leaderboardText(
  hass: unknown,
  rank: HassEntity | undefined,
  total: HassEntity | undefined,
): string | null {
  const rankText = formatStateText(hass, rank);
  const totalText = formatStateText(hass, total);
  if (rankText === null || totalText === null) return null;
  return localize(hass, "leaderboard", { rank: rankText, total: totalText });
}
