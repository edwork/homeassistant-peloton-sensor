// Minimal local types for the parts of the Home Assistant frontend the card
// reads, and the card's own configuration and view model. Everything that
// comes from Home Assistant is typed loosely on purpose: the card checks the
// shape of each value before using it.

/** One part of a formatted value (src/types.ts ValuePart in the frontend). */
export interface ValuePart {
  type: "value" | "literal" | "unit";
  value: string;
}

/** A state object from hass.states. */
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
}

/** An entry of hass.entities (EntityRegistryDisplayEntry). */
export interface EntityRegistryEntry {
  entity_id: string;
  device_id?: string;
  platform?: string;
  translation_key?: string;
  display_precision?: number;
}

/** An entry of hass.devices (DeviceRegistryEntry). */
export interface DeviceRegistryEntry {
  id: string;
  identifiers?: [string, string][];
  name?: string | null;
  name_by_user?: string | null;
  disabled_by?: string | null;
}

/** The subset of the frontend's HomeAssistant object the card uses. */
export interface HomeAssistant {
  states: Record<string, HassEntity | undefined>;
  // Both registries start as null until the first registry message arrives.
  entities: Record<string, EntityRegistryEntry> | null;
  devices: Record<string, DeviceRegistryEntry> | null;
  language?: string;
  locale?: { language?: string };
  themes?: unknown;
  connected?: boolean;
  formatEntityState?: (stateObj: HassEntity, state?: string) => string;
  formatEntityStateToParts?: (stateObj: HassEntity, state?: string) => ValuePart[];
  formatEntityAttributeValue?: (stateObj: HassEntity, attribute: string, value?: unknown) => string;
}

/** A Lovelace action configuration, such as {action: "more-info"}. */
export type ActionConfig = Readonly<Record<string, unknown>>;

/** The metric keys of the `metrics` option, in the editor's order. */
export const METRIC_KEYS = [
  "output",
  "cadence",
  "resistance",
  "heart_rate",
  "speed",
  "pace",
  "incline",
  "stroke_rate",
  "split_pace",
] as const;

export type MetricKey = (typeof METRIC_KEYS)[number];

export type Variant = "full" | "compact";

/** The card configuration after validateConfig: defaults applied, frozen. */
export interface CardConfig {
  readonly type: string;
  readonly device_id?: string;
  readonly name?: string;
  readonly variant: Variant;
  /** Empty means automatic by workout type. */
  readonly metrics: readonly MetricKey[];
  readonly show_image: boolean;
  readonly show_logo: boolean;
  readonly show_totals: boolean;
  readonly show_leaderboard: boolean;
  readonly tap_action?: ActionConfig;
  /** {translation_key: entity_id} overrides, from YAML only. */
  readonly entities: Readonly<Record<string, string>>;
}

/** Why the card cannot show a rider. */
export type ProblemStatus =
  | "no_device"
  | "choose_device"
  | "device_not_found"
  | "device_disabled"
  | "workout_missing";

/** The result of resolve(): which device and entities the card shows. */
export type Resolution =
  | { readonly status: "loading" }
  | { readonly status: ProblemStatus }
  | {
      readonly status: "ok";
      readonly deviceId: string;
      readonly name: string;
      /** translation_key to entity_id, with the config overrides applied. */
      readonly map: Readonly<Record<string, string>>;
      /** Entity ids whose state changes can change what the card shows. */
      readonly watched: readonly string[];
    };

/** The display phase, in the order the rules are checked. */
export type Phase =
  | "loading"
  | "problem"
  | "waiting"
  | "unavailable"
  | "none"
  | "paused"
  | "active"
  | "idle";

/**
 * Color role of the chip and the compact ring. The renderer maps it to
 * --peloton-active-color, --peloton-paused-color, --peloton-idle-color,
 * --state-unavailable-color and --warning-color; "none" means no color.
 */
export type Tone = "active" | "paused" | "idle" | "unavailable" | "warning" | "none";

/** A formatted value, ready for text bindings. */
export interface ValueView {
  /** Value, literal and unit parts; render unit parts at a smaller size. */
  readonly parts: readonly ValuePart[];
  /** All parts joined. */
  readonly text: string;
  /** False when the value is unknown; the parts are then an em dash. */
  readonly known: boolean;
  /** Accessible text: the value, or "No value" when unknown. */
  readonly label: string;
}

/** A labelled value, such as "Avg 150 W" or a totals item. */
export interface StatView {
  readonly key: string;
  readonly label: string;
  readonly value: ValueView;
  /** Entity for more-info on tap, or null when it is not mapped. */
  readonly entityId: string | null;
}

/** One metric tile. */
export interface TileView {
  readonly key: MetricKey;
  /** Metric name, such as "Output". */
  readonly label: string;
  /** Label of the large value: null for the current value, "Avg" otherwise. */
  readonly valueLabel: string | null;
  readonly value: ValueView;
  /** Second line items: "Avg" and "Max" (or "Best") while active, else "Max". */
  readonly secondary: readonly StatView[];
  /** The second line as one string, items joined with " \u00b7 ". */
  readonly secondaryText: string;
  /** Entity for more-info on tap; a tile always has one mapped sensor. */
  readonly entityId: string;
  /** True for the first tile; it spans two columns when the card is wide. */
  readonly primary: boolean;
}

/** The chip next to the title. */
export interface ChipView {
  readonly text: string;
  readonly tone: Tone;
}

/** The header of the full variant. */
export interface HeaderView {
  /** Rider name. */
  readonly name: string;
  /** Discipline icon (mdi:...) in the workout phases, else null. */
  readonly icon: string | null;
  /** Class title in the workout phases, else null. */
  readonly title: string | null;
  /** Instructor, discipline and time joined with " \u00b7 ", or null. */
  readonly classLine: string | null;
  /** "Started ..." while a workout runs, "Ended ..." after it, or null. */
  readonly timeLine: string | null;
  readonly chip: ChipView | null;
}

/** The configuration for the frontend's hass-action event (tap). */
export interface HeaderAction {
  readonly entity: string;
  readonly tap_action: ActionConfig;
}

/** The compact variant's single row. */
export interface CompactView {
  /** Icon in the ring; always set. */
  readonly icon: string;
  readonly tone: Tone;
  /** Status text; also used for title and aria-label. Empty while loading. */
  readonly text: string;
}

/**
 * Everything the renderer needs, derived by computeView(hass, config).
 *
 * Fields that do not apply to a phase are null or empty, so the renderer
 * only checks for presence:
 * - loading: everything empty.
 * - problem: problem and message set, tone "warning"; no header, no action.
 * - waiting, unavailable, none: header with the name (chip only for
 *   unavailable), message set; none also has detail (total workouts).
 * - active, paused, idle: header with title, chip and class line, tiles,
 *   totals and leaderboard as configured, image when allowed.
 */
export interface CardView {
  readonly phase: Phase;
  readonly variant: Variant;
  /** Set only in the problem phase. */
  readonly problem: ProblemStatus | null;
  readonly header: HeaderView | null;
  /** Body text: the warning, or the waiting, unavailable or none message. */
  readonly message: string | null;
  /** Extra item under the message (none phase: total workouts). */
  readonly detail: StatView | null;
  readonly tiles: readonly TileView[];
  /** True while paused: tile values use --secondary-text-color. */
  readonly tilesMuted: boolean;
  /** Pre-roll hint, or null. */
  readonly hint: string | null;
  /** Totals row items; empty when hidden. */
  readonly totals: readonly StatView[];
  /** "Rank R of T", or null when hidden or unknown. */
  readonly leaderboard: string | null;
  /** Entity for the leaderboard's more-info, or null. */
  readonly leaderboardEntityId: string | null;
  /** Class image URL (https only), or null. The width rule is CSS. */
  readonly image: string | null;
  /** Full variant with show_logo: the Peloton logo leads the header. */
  readonly logo: boolean;
  readonly compact: CompactView;
  /** Header (full) or row (compact) tap action, or null for no action. */
  readonly action: HeaderAction | null;
  /** Text announced when this phase is entered; see announcement(). */
  readonly announce: string | null;
  /** Entity ids to compare in shouldUpdate. */
  readonly watched: readonly string[];
}
