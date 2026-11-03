// computeView: everything the card shows, derived from hass and the config.
import { DEFAULTS, VARIANTS, validateConfig } from "./config";
import {
  autoMetrics,
  DEFAULT_ICON,
  disciplineIcon,
  disciplineName,
  formatStateText,
  formatValue,
  isPaceMetric,
  leaderboardText,
  metricDiscipline,
  WARNING_ICON,
} from "./format";
import { localize } from "./localize";
import { attributes, known, LEADERBOARD_KEYS, resolve, stateObj, TOTAL_KEYS } from "./resolve";
import {
  type CardConfig,
  type CardView,
  type ChipView,
  type HassEntity,
  type HeaderAction,
  type HeaderView,
  METRIC_KEYS,
  type MetricKey,
  type Phase,
  type ProblemStatus,
  type StatView,
  type TileView,
  type Tone,
} from "./types";

type EntityMap = Readonly<Record<string, string>>;
type WorkoutPhase = "active" | "paused" | "idle";

const ANNOUNCE: Partial<Record<Phase, string>> = {
  active: "announce.started",
  paused: "announce.paused",
  idle: "announce.finished",
};

const TOTAL_LABELS: Readonly<Record<string, string>> = {
  total_output: "total.total_output",
  distance: "total.distance",
  total_calories: "total.total_calories",
  duration: "total.duration",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function entityOf(map: EntityMap, key: string): string | undefined {
  return Object.hasOwn(map, key) ? map[key] : undefined;
}

/** Use a validated config as it is; validate anything else, else defaults. */
function normalize(config: unknown): CardConfig {
  if (
    isRecord(config) &&
    typeof config.variant === "string" &&
    (VARIANTS as readonly string[]).includes(config.variant) &&
    Array.isArray(config.metrics) &&
    isRecord(config.entities)
  ) {
    return config as unknown as CardConfig;
  }
  try {
    return validateConfig(config);
  } catch {
    return DEFAULTS;
  }
}

function base(config: CardConfig, phase: Phase): CardView {
  return {
    phase,
    variant: config.variant,
    problem: null,
    header: null,
    message: null,
    detail: null,
    tiles: [],
    tilesMuted: false,
    hint: null,
    totals: [],
    leaderboard: null,
    leaderboardEntityId: null,
    image: null,
    compact: { icon: DEFAULT_ICON, tone: "none", text: "" },
    action: null,
    announce: null,
    watched: [],
  };
}

function stat(hass: unknown, map: EntityMap, key: string, label: string, pace = false): StatView {
  const entityId = entityOf(map, key) ?? null;
  return {
    key,
    label,
    value: formatValue(hass, stateObj(hass, entityId ?? undefined), { pace }),
    entityId,
  };
}

/** Any metric average, total output or distance is known. */
export function sampleSignal(hass: unknown, map: EntityMap): boolean {
  return (
    METRIC_KEYS.some((key) => known(hass, map, `${key}_average`)) ||
    known(hass, map, "total_output") ||
    known(hass, map, "distance")
  );
}

function mapped(map: EntityMap, key: MetricKey): boolean {
  return ["current", "average", "max"].some((kind) => Object.hasOwn(map, `${key}_${kind}`));
}

/** Metrics of the tiles: explicit or automatic, then the visibility rules. */
export function visibleMetrics(
  hass: unknown,
  config: CardConfig,
  map: EntityMap,
  phase: WorkoutPhase,
  workoutType: string | undefined,
): MetricKey[] {
  const explicit = config.metrics.length > 0;
  const candidates = (explicit ? config.metrics : autoMetrics(workoutType)).filter((key) =>
    mapped(map, key),
  );
  if (explicit) return candidates;
  if (phase === "idle") return candidates.filter((key) => known(hass, map, `${key}_average`));
  if (!sampleSignal(hass, map)) return candidates;
  return candidates.filter(
    (key) => known(hass, map, `${key}_current`) || known(hass, map, `${key}_average`),
  );
}

function tile(
  hass: unknown,
  map: EntityMap,
  key: MetricKey,
  phase: WorkoutPhase,
  primary: boolean,
): TileView {
  const pace = isPaceMetric(key);
  const averageLabel = localize(hass, "stat.average");
  const maxLabel = localize(hass, pace ? "stat.best" : "stat.max");
  const sensor = (kind: string, label: string) => stat(hass, map, `${key}_${kind}`, label, pace);
  const live = phase === "active";
  const main = live ? sensor("current", "") : sensor("average", averageLabel);
  const secondary = (live ? [sensor("average", averageLabel)] : [])
    .concat(sensor("max", maxLabel))
    .filter((item) => item.entityId !== null);
  const order = live ? ["current", "average", "max"] : ["average", "max", "current"];
  const target = order.map((kind) => entityOf(map, `${key}_${kind}`)).find(Boolean);
  return {
    key,
    label: localize(hass, `metric.${key}`),
    valueLabel: live ? null : averageLabel,
    value: main.value,
    secondary,
    secondaryText: secondary
      .map((item) => `${item.label} ${item.value.text}`)
      .join(localize(hass, "separator")),
    // A tile is shown only when one of its sensors is mapped.
    entityId: target ?? "",
    primary,
  };
}

function chip(hass: unknown, phase: WorkoutPhase | "unavailable"): ChipView {
  const tone: Tone = phase;
  return { text: localize(hass, `chip.${phase}`), tone };
}

function problemView(hass: unknown, config: CardConfig, status: ProblemStatus): CardView {
  return {
    ...base(config, "problem"),
    problem: status,
    message: localize(hass, `problem.${status}`),
    compact: {
      icon: WARNING_ICON,
      tone: "warning",
      text: localize(hass, `problem_short.${status}`),
    },
  };
}

function plainHeader(name: string, chipView: ChipView | null = null): HeaderView {
  return { name, icon: null, title: null, classLine: null, chip: chipView };
}

function workoutView(
  hass: unknown,
  config: CardConfig,
  map: EntityMap,
  workout: HassEntity,
  phase: WorkoutPhase,
  common: Pick<CardView, "action" | "watched">,
  name: string,
): CardView {
  const attrs = attributes(workout);
  const workoutType = str(attrs.workout_type);
  const discipline = workoutType ? disciplineName(hass, workout, workoutType) : undefined;
  const title = str(attrs.ride_title) ?? discipline ?? localize(hass, "title.workout");
  const icon = disciplineIcon(workoutType);
  const start = formatStateText(hass, stateObj(hass, entityOf(map, "start_time")));
  const end = formatStateText(hass, stateObj(hass, entityOf(map, "end_time")));
  const time =
    phase === "idle" && end !== null ? localize(hass, "class_line.ended", { time: end }) : start;
  const separator = localize(hass, "separator");
  const classItems = [str(attrs.instructor), discipline, time ?? undefined].filter(
    (item): item is string => item !== undefined,
  );

  const tiles = visibleMetrics(hass, config, map, phase, workoutType).map((key, index) =>
    tile(hass, map, key, phase, index === 0),
  );

  const totals = config.show_totals
    ? TOTAL_KEYS.filter((key) => Object.hasOwn(map, key)).map((key) =>
        stat(hass, map, key, localize(hass, TOTAL_LABELS[key])),
      )
    : [];

  const [rankKey, totalKey] = LEADERBOARD_KEYS;
  const leaderboard = config.show_leaderboard
    ? leaderboardText(
        hass,
        stateObj(hass, entityOf(map, rankKey)),
        stateObj(hass, entityOf(map, totalKey)),
      )
    : null;

  const imageUrl = str(attrs.workout_image);
  const image =
    config.variant === "full" && config.show_image && imageUrl?.startsWith("https://")
      ? imageUrl
      : null;

  let compactText: string;
  if (phase === "active") {
    const values = tiles
      .slice(0, 2)
      .filter((item) => item.value.known)
      .map((item) => item.value.text);
    compactText = values.length
      ? localize(hass, "compact.active_values", { values: values.join(", ") })
      : localize(hass, "compact.active");
  } else if (phase === "paused") {
    compactText = localize(hass, "compact.paused");
  } else {
    const details = [discipline ?? localize(hass, "title.workout"), end ?? start ?? undefined]
      .filter((item): item is string => item !== undefined)
      .join(", ");
    compactText = localize(hass, "compact.idle", { details });
  }

  return {
    ...base(config, phase),
    ...common,
    header: {
      name,
      icon,
      title,
      classLine: classItems.length ? classItems.join(separator) : null,
      chip: chip(hass, phase),
    },
    tiles,
    tilesMuted: phase === "paused",
    hint:
      phase === "active" && metricDiscipline(workoutType) && !sampleSignal(hass, map)
        ? localize(hass, "hint.preroll")
        : null,
    totals,
    leaderboard,
    leaderboardEntityId: leaderboard !== null ? (entityOf(map, rankKey) ?? null) : null,
    image,
    compact: { icon, tone: phase, text: compactText },
    announce: localize(hass, ANNOUNCE[phase] as string),
  };
}

/**
 * Derive the card's display from hass and the config. Pure and total: it
 * never throws, whatever the shape of hass, and returns a new plain object.
 * The phase is the first matching row of the design's rule table: loading,
 * problem, waiting, unavailable, none, paused, active, idle.
 */
export function computeView(hass: unknown, config: CardConfig): CardView {
  const cfg = normalize(config);
  const resolution = resolve(hass, cfg);
  if (resolution.status === "loading") return base(cfg, "loading");
  if (resolution.status !== "ok") return problemView(hass, cfg, resolution.status);

  const { map, name, watched } = resolution;
  const workoutId = map.workout;
  const tapAction = isRecord(cfg.tap_action) ? cfg.tap_action : { action: "more-info" };
  const action: HeaderAction = { entity: workoutId, tap_action: tapAction };
  const common = { action, watched };
  const workout = stateObj(hass, workoutId);

  if (workout === undefined) {
    return {
      ...base(cfg, "waiting"),
      ...common,
      header: plainHeader(name),
      message: localize(hass, "message.waiting"),
      compact: { icon: DEFAULT_ICON, tone: "none", text: localize(hass, "compact.waiting") },
    };
  }
  if (workout.state !== "on" && workout.state !== "off") {
    return {
      ...base(cfg, "unavailable"),
      ...common,
      header: plainHeader(name, chip(hass, "unavailable")),
      message: localize(hass, "message.unavailable"),
      compact: {
        icon: DEFAULT_ICON,
        tone: "unavailable",
        text: localize(hass, "compact.unavailable"),
      },
    };
  }
  const attrs = attributes(workout);
  if (workout.state === "off" && typeof attrs.workout_type !== "string") {
    const total = known(hass, map, "total_workouts")
      ? stat(hass, map, "total_workouts", localize(hass, "total.total_workouts"))
      : null;
    return {
      ...base(cfg, "none"),
      ...common,
      header: plainHeader(name),
      message: localize(hass, "message.none"),
      detail: total,
      compact: { icon: DEFAULT_ICON, tone: "none", text: localize(hass, "compact.none") },
    };
  }
  let phase: WorkoutPhase = "idle";
  if (workout.state === "on") phase = attrs.paused === true ? "paused" : "active";
  return workoutView(hass, cfg, map, workout, phase, common, name);
}

/**
 * Text for the live region when the phase changes from `previous` to
 * `next`, or null. Silent on the first render, for unchanged phases, and for
 * changes from or to phases without a workout (loading, problem, waiting,
 * unavailable), so a reconnect is not announced as a new workout.
 */
export function announcement(
  hass: unknown,
  previous: Phase | undefined,
  next: Phase,
): string | null {
  if (previous === undefined || previous === next) return null;
  if (next === "active" && previous === "paused") return localize(hass, "announce.resumed");
  if ((next === "active" || next === "paused") && (previous === "idle" || previous === "none")) {
    return localize(hass, ANNOUNCE[next] as string);
  }
  if (next === "paused" && previous === "active") return localize(hass, "announce.paused");
  if (next === "idle" && (previous === "active" || previous === "paused")) {
    return localize(hass, "announce.finished");
  }
  return null;
}

/** The card's getGridOptions() for the sections view. */
export function gridOptions(
  config: Pick<CardConfig, "variant">,
): Readonly<Record<string, unknown>> {
  return config.variant === "compact"
    ? { columns: 6, rows: 1, min_columns: 3, max_rows: 2 }
    : { columns: 12, rows: "auto", min_columns: 6, min_rows: 3 };
}

/** The card's getCardSize() for the masonry view. */
export function cardSize(
  config: Pick<CardConfig, "variant" | "show_totals">,
  view: Pick<CardView, "tiles"> | undefined,
): number {
  if (config.variant === "compact") return 1;
  const tiles = view?.tiles.length ?? 0;
  return Math.max(2, 2 + 2 * Math.ceil(tiles / 4) + (config.show_totals ? 1 : 0));
}
