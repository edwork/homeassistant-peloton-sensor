import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { CARD_TYPE } from "../src/config";
import { entitySuggestion } from "../src/resolve";
import type { HassEntity, HomeAssistant } from "../src/types";
import { PelotonWorkoutCard } from "../src/workout-card";
import {
  entityIdOf,
  hassWith,
  makeHass,
  type RiderOptions,
  rider,
  stateFor,
  WORKOUT_TYPE_NAMES,
} from "./fake-hass";

const START = "2026-11-02T16:00:00+00:00";
const END = "2026-11-02T16:45:00+00:00";
const IMAGE = "https://example.com/class.png";

const CYCLING = {
  workout_type: "cycling",
  ride_title: "30 min Pop Ride",
  instructor: "Alex",
  workout_image: IMAGE,
  paused: false,
};

const SAMPLES = {
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

const RIDING: RiderOptions = {
  states: { workout: "on", start_time: START, ...SAMPLES },
  workout: CYCLING,
};
const PAUSED: RiderOptions = { ...RIDING, workout: { ...CYCLING, paused: true } };
const FINISHED: RiderOptions = {
  states: { workout: "off", start_time: START, end_time: END, ...SAMPLES },
  workout: CYCLING,
};
const IDLE_NO_WORKOUTS: RiderOptions = {
  states: { workout: "off", total_workouts: "12" },
  workout: {},
};

type Card = PelotonWorkoutCard;

beforeAll(() => {
  customElements.define(CARD_TYPE, PelotonWorkoutCard);
});

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

async function mount(
  hass: HomeAssistant | undefined,
  raw: Record<string, unknown> = {},
): Promise<Card> {
  const card = document.createElement(CARD_TYPE) as Card;
  card.setConfig({ type: `custom:${CARD_TYPE}`, ...raw });
  if (hass !== undefined) card.hass = hass;
  document.body.append(card);
  await card.updateComplete;
  return card;
}

async function update(card: Card, hass: HomeAssistant): Promise<void> {
  card.hass = hass;
  await card.updateComplete;
}

function root(card: Card): ShadowRoot {
  if (!card.shadowRoot) throw new Error("no shadow root");
  return card.shadowRoot;
}

function find<T extends Element = HTMLElement>(card: Card, selector: string): T | null {
  return root(card).querySelector<T>(selector) as T | null;
}

function all(card: Card, selector: string): HTMLElement[] {
  return [...root(card).querySelectorAll<HTMLElement>(selector)];
}

function text(node: Node | null | undefined): string {
  return (node?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Visible text: without the visually hidden helpers. */
function visibleText(node: Element | null): string {
  if (!node) return "";
  const copy = node.cloneNode(true) as Element;
  for (const hidden of copy.querySelectorAll(".sr-only")) hidden.remove();
  return text(copy);
}

function liveRegion(card: Card): HTMLElement {
  const region = find(card, '[role="status"]');
  if (!region) throw new Error("no live region");
  return region;
}

/** A copy of hass with some states replaced. */
function withStates(hass: HomeAssistant, states: Record<string, HassEntity>): HomeAssistant {
  return { ...hass, states: { ...hass.states, ...states } };
}

function sensor(key: string, state: string): Record<string, HassEntity> {
  const entityId = entityIdOf(key);
  return { [entityId]: stateFor(entityId, key, state) };
}

function workoutState(state: string, attributes: Record<string, unknown>) {
  const entityId = entityIdOf("workout");
  return { [entityId]: stateFor(entityId, "workout", state, attributes) };
}

function events(type: string): CustomEvent[] {
  const seen: CustomEvent[] = [];
  document.addEventListener(type, (ev) => seen.push(ev as CustomEvent));
  return seen;
}

describe("full variant", () => {
  it("renders an empty block while loading", async () => {
    const card = await mount(undefined);
    expect(find(card, "ha-card")?.className).toContain("full");
    expect(find(card, ".loading")).not.toBeNull();
    expect(find(card, '[role="button"]')).toBeNull();
    expect(all(card, "button")).toHaveLength(0);
    expect(text(find(card, ".root"))).toBe("");
  });

  it.each([
    [
      "no_device",
      () => makeHass({ riders: [] }),
      {},
      "No Peloton account found. Add the Peloton integration first.",
    ],
    [
      "choose_device",
      () =>
        makeHass({
          riders: [rider(), rider({ deviceId: "device-2", prefix: "john_on_peloton" })],
        }),
      {},
      "Choose a Peloton account in the card settings.",
    ],
    [
      "device_not_found",
      () => hassWith(),
      { device_id: "missing" },
      "The selected Peloton account was not found.",
    ],
    [
      "device_disabled",
      () => hassWith({ disabled: true }),
      { device_id: "device-1" },
      "The selected Peloton account is disabled.",
    ],
    [
      "workout_missing",
      () => hassWith({ disabledKeys: ["workout"] }),
      {},
      "The Peloton workout sensor is disabled or not set up yet.",
    ],
  ])("renders the %s warning without actions", async (_status, hass, raw, message) => {
    const card = await mount(hass(), raw);
    expect(find(card, "ha-card")?.classList.contains("problem")).toBe(true);
    expect(text(find(card, ".problem-text"))).toBe(message);
    expect(find(card, "ha-icon")?.getAttribute("icon")).toBe("mdi:alert-circle-outline");
    expect(find(card, '[role="button"]')).toBeNull();
    expect(all(card, "button")).toHaveLength(0);
  });

  it("renders waiting with the name and an action", async () => {
    const card = await mount(hassWith({ noState: ["workout"] }));
    const header = find(card, ".header");
    expect(header?.getAttribute("role")).toBe("button");
    expect(header?.getAttribute("tabindex")).toBe("0");
    expect(text(find(card, ".title"))).toBe("Jane on Peloton");
    expect(find(card, ".chip")).toBeNull();
    expect(text(find(card, ".message"))).toBe("Waiting for Peloton data.");
    expect(find(card, ".tiles")).toBeNull();
  });

  it("renders unavailable with a chip and no title", async () => {
    const card = await mount(hassWith({ states: { workout: "unavailable" }, workout: CYCLING }));
    expect(text(find(card, ".title"))).toBe("Jane on Peloton");
    const chip = find(card, ".chip");
    expect(text(chip)).toBe("Unavailable");
    expect(chip?.classList.contains("tone-unavailable")).toBe(true);
    expect(text(find(card, ".message"))).toBe(
      "Peloton data is unavailable. Values return when the connection recovers.",
    );
    expect(root(card).textContent).not.toContain("30 min Pop Ride");
    expect(find(card, ".tiles")).toBeNull();
    expect(find(card, ".footer")).toBeNull();
  });

  it("renders no workouts with the total workouts", async () => {
    const card = await mount(hassWith(IDLE_NO_WORKOUTS));
    expect(text(find(card, ".message"))).toBe("No workouts yet.");
    const detail = find(card, "button.stat");
    expect(detail?.getAttribute("aria-label")).toBe("Total workouts: 12");
    expect(detail?.dataset.entity).toBe(entityIdOf("total_workouts"));
    expect(find(card, ".tiles")).toBeNull();
  });

  it("renders an active ride", async () => {
    const card = await mount(hassWith(RIDING), { name: "Jane" });
    expect(text(find(card, ".name"))).toBe("Jane");
    expect(text(find(card, ".title"))).toBe("30 min Pop Ride");
    const chip = find(card, ".chip");
    expect(text(chip)).toBe("In progress");
    expect(chip?.classList.contains("tone-active")).toBe(true);
    expect(text(find(card, ".class-line"))).toBe(`Alex \u00b7 ${WORKOUT_TYPE_NAMES.cycling}`);
    expect(text(find(card, ".time-line"))).toBe(`Started at ${START}`);
    // The Peloton logo leads the header instead of the discipline icon.
    const logo = find(card, ".header svg.logo");
    expect(logo?.getAttribute("aria-hidden")).toBe("true");
    expect(logo?.querySelector("path")?.getAttribute("d")).toMatch(/^m 31\.52468,295\.67403 /);
    expect(find(card, ".header ha-icon")).toBeNull();
    expect(find(card, ".tiles")?.classList.contains("count-3")).toBe(true);

    const tiles = all(card, "button.tile");
    expect(tiles.map((tile) => tile.getAttribute("aria-label"))).toEqual([
      "Output: 182 W, Avg 150 W, Max 301 W",
      "Cadence: 85 rpm, Avg 80 rpm, Max 110 rpm",
      "Resistance: 40%, Avg 38%, Max 55%",
    ]);
    expect(tiles.map((tile) => tile.classList.contains("primary"))).toEqual([true, false, false]);
    expect(text(tiles[0].querySelector("dt"))).toBe("Output");
    expect(text(tiles[0].querySelector(".main"))).toBe("182 W");
    expect(text(tiles[0].querySelector(".unit"))).toBe("W");
    expect(text(tiles[0].querySelector(".secondary"))).toBe("Avg 150 W \u00b7 Max 301 W");
    expect(tiles[0].querySelector("dl dd")).not.toBeNull();
    expect(find(card, ".tiles")?.classList.contains("muted")).toBe(false);
    expect(find(card, ".hint")).toBeNull();

    expect(all(card, ".totals button").map((item) => item.getAttribute("aria-label"))).toEqual([
      "Total output: 120 kJ",
      "Distance: 5.2 mi",
      "Calories: 210 kcal",
      "Class length: 30 min",
    ]);
    expect(text(find(card, ".leaderboard"))).toBe("Rank 1234 of 5678");

    const image = find<HTMLImageElement>(card, ".image img");
    expect(image?.getAttribute("src")).toBe(IMAGE);
    expect(image?.getAttribute("alt")).toBe("");
    expect(image?.getAttribute("loading")).toBe("lazy");
    expect(image?.getAttribute("decoding")).toBe("async");
    expect(image?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("renders the pre-roll hint and dashes before the first data", async () => {
    const card = await mount(
      hassWith({ states: { workout: "on", start_time: START }, workout: CYCLING }),
    );
    expect(text(find(card, ".hint"))).toBe("Waiting for the first data from Peloton");
    const tiles = all(card, "button.tile");
    expect(tiles).toHaveLength(4);
    expect(tiles[0].getAttribute("aria-label")).toBe(
      "Output: No value, Avg No value, Max No value",
    );
    const dash = tiles[0].querySelector(".main .dash");
    expect(text(dash)).toBe("\u2014");
    expect(dash?.getAttribute("aria-hidden")).toBe("true");
    expect(text(tiles[0].querySelector(".main .sr-only"))).toBe("No value");
    expect(find(card, ".leaderboard")).toBeNull();
  });

  it("renders a strength class without metrics and without the hint", async () => {
    const card = await mount(
      hassWith({ states: { workout: "on" }, workout: { workout_type: "strength" } }),
    );
    expect(find(card, ".hint")).toBeNull();
    expect(text(find(card, ".title"))).toBe(WORKOUT_TYPE_NAMES.strength);
    expect(find(card, ".header svg.logo")).not.toBeNull();
    expect(find(card, ".tiles")?.classList.contains("count-1")).toBe(true);
    expect(all(card, "button.tile").map((tile) => text(tile.querySelector("dt")))).toEqual([
      "Heart rate",
    ]);
  });

  it("renders a paused ride with averages", async () => {
    const card = await mount(hassWith(PAUSED));
    const chip = find(card, ".chip");
    expect(text(chip)).toBe("Paused");
    expect(chip?.classList.contains("tone-paused")).toBe(true);
    expect(find(card, ".tiles")?.classList.contains("muted")).toBe(true);
    const tile = all(card, "button.tile")[0];
    expect(tile.getAttribute("aria-label")).toBe("Output: Avg 150 W, Max 301 W");
    expect(text(tile.querySelector(".value-label"))).toBe("Avg");
    expect(text(tile.querySelector(".main"))).toBe("Avg 150 W");
    expect(text(tile.querySelector(".secondary"))).toBe("Max 301 W");
  });

  it("renders the last workout", async () => {
    const card = await mount(hassWith(FINISHED));
    const chip = find(card, ".chip");
    expect(text(chip)).toBe("Last workout");
    expect(chip?.classList.contains("tone-idle")).toBe(true);
    expect(text(find(card, ".class-line"))).toBe(`Alex \u00b7 ${WORKOUT_TYPE_NAMES.cycling}`);
    expect(text(find(card, ".time-line"))).toBe(`Ended at ${END}`);
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toBe(
      "Output: Avg 150 W, Max 301 W",
    );
  });

  it("shows the discipline icon without the logo", async () => {
    const card = await mount(
      hassWith({ states: { workout: "on" }, workout: { workout_type: "strength" } }),
      { show_logo: false },
    );
    expect(find(card, ".header svg.logo")).toBeNull();
    expect(find(card, ".header ha-icon")?.getAttribute("icon")).toBe("mdi:dumbbell");
  });

  it("shows no logo in the compact variant", async () => {
    const card = await mount(hassWith(RIDING), { variant: "compact" });
    expect(find(card, "svg.logo")).toBeNull();
    expect(find(card, ".row .text .name")).not.toBeNull();
    expect(find(card, ".row .text .status")).not.toBeNull();
  });

  it("honours the content options", async () => {
    const card = await mount(hassWith(RIDING), {
      show_image: false,
      show_totals: false,
      show_leaderboard: false,
      metrics: ["heart_rate", "output"],
    });
    expect(find(card, ".image")).toBeNull();
    expect(find(card, ".footer")).toBeNull();
    expect(all(card, "button.tile").map((tile) => text(tile.querySelector("dt")))).toEqual([
      "Heart rate",
      "Output",
    ]);
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toBe(
      "Heart rate: No value, Avg No value, Max No value",
    );
  });

  it("formats pace tiles as minutes and seconds", async () => {
    const card = await mount(
      hassWith({
        states: { workout: "on", pace_current: "8.5", pace_average: "9.25", pace_max: "7.999" },
        workout: { workout_type: "running" },
      }),
      { metrics: ["pace"] },
    );
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toBe(
      "Pace: 8:30/mi, Avg 9:15/mi, Best 8:00/mi",
    );
  });
});

describe("compact variant", () => {
  it.each([
    ["active", RIDING, "In progress: 182 W, 85 rpm", "active"],
    ["paused", PAUSED, "Paused", "paused"],
    ["idle", FINISHED, `Last workout: ${WORKOUT_TYPE_NAMES.cycling}, at ${END}`, "idle"],
    ["none", IDLE_NO_WORKOUTS, "No workouts yet", "none"],
    ["waiting", { noState: ["workout"] } as RiderOptions, "Waiting for Peloton data", "none"],
    [
      "unavailable",
      { states: { workout: "unknown" } } as RiderOptions,
      "Unavailable",
      "unavailable",
    ],
  ])("renders %s in one row", async (_phase, options, status, tone) => {
    const card = await mount(hassWith(options), { variant: "compact" });
    expect(find(card, "ha-card")?.className).toContain("compact");
    const row = find(card, ".row");
    expect(row?.getAttribute("role")).toBe("button");
    expect(row?.getAttribute("tabindex")).toBe("0");
    expect(text(row?.querySelector(".name"))).toBe("Jane on Peloton");
    expect(text(row?.querySelector(".status"))).toBe(status);
    expect(row?.getAttribute("title")).toBe(`Jane on Peloton: ${status}`);
    expect(row?.getAttribute("aria-label")).toBe(`Jane on Peloton: ${status}`);
    expect(row?.querySelector(".ring")?.classList.contains(`tone-${tone}`)).toBe(true);
    expect(find(card, ".image")).toBeNull();
    expect(all(card, "button")).toHaveLength(0);
  });

  it("renders the short warning without an action", async () => {
    const card = await mount(makeHass({ riders: [] }), { variant: "compact" });
    const row = find(card, ".row");
    expect(row?.getAttribute("role")).toBeNull();
    expect(row?.getAttribute("tabindex")).toBeNull();
    expect(row?.getAttribute("aria-label")).toBeNull();
    expect(row?.getAttribute("title")).toBe("No Peloton account");
    expect(row?.querySelector(".name")).toBeNull();
    expect(text(row?.querySelector(".status"))).toBe("No Peloton account");
    expect(row?.querySelector("ha-icon")?.getAttribute("icon")).toBe("mdi:alert-circle-outline");
    expect(find(card, "ha-card")?.classList.contains("problem")).toBe(true);
  });

  it("renders an empty row while loading", async () => {
    const card = await mount(undefined, { variant: "compact" });
    expect(find(card, ".row")).not.toBeNull();
    expect(visibleText(find(card, ".root"))).toBe("");
    expect(find(card, '[role="button"]')).toBeNull();
  });
});

describe("escaping", () => {
  it("renders markup in Peloton text as text", async () => {
    const title = '<b>Bold</b><img src="x" onerror="alert(1)">';
    const card = await mount(
      hassWith({
        ...RIDING,
        workout: { ...CYCLING, ride_title: title, instructor: "<i>Alex</i>" },
      }),
    );
    expect(find(card, ".title")?.textContent).toBe(title);
    expect(text(find(card, ".class-line"))).toContain("<i>Alex</i>");
    expect(find(card, "b")).toBeNull();
    expect(find(card, "i")).toBeNull();
    expect(all(card, "img")).toHaveLength(1);
    expect(find(card, "img[onerror]")).toBeNull();
  });

  it.each([
    "http://example.com/class.png",
    "javascript:alert(1)",
    'https://example.com/a.png" onerror="alert(1)',
  ])("shows an https image URL only as an attribute: %s", async (url) => {
    const card = await mount(hassWith({ ...RIDING, workout: { ...CYCLING, workout_image: url } }));
    const images = all(card, "img");
    if (url.startsWith("https://")) {
      expect(images).toHaveLength(1);
      expect(images[0].getAttribute("src")).toBe(url);
      expect(images[0].getAttribute("onerror")).toBeNull();
    } else {
      expect(images).toHaveLength(0);
    }
  });
});

describe("image", () => {
  it("hides an image that failed to load until the URL changes", async () => {
    const hass = hassWith(RIDING);
    const card = await mount(hass);
    find(card, ".image img")?.dispatchEvent(new Event("error"));
    await card.updateComplete;
    expect(find(card, ".image")).toBeNull();

    await update(card, withStates(hass, sensor("output_current", "190")));
    expect(find(card, ".image")).toBeNull();

    const other = "https://example.com/other.png";
    await update(card, withStates(hass, workoutState("on", { ...CYCLING, workout_image: other })));
    expect(find(card, ".image img")?.getAttribute("src")).toBe(other);
  });
});

describe("update filter", () => {
  async function counted(hass: HomeAssistant, raw: Record<string, unknown> = {}) {
    const card = await mount(hass, raw);
    const render = vi.spyOn(card as unknown as { render(): unknown }, "render");
    return { card, render };
  }

  it("does not re-render for an unrelated entity", async () => {
    const hass = hassWith(RIDING);
    const { card, render } = await counted(hass);
    await update(card, {
      ...hass,
      states: { ...hass.states, "light.kitchen": stateFor("light.kitchen", "light", "on") },
    });
    expect(render).not.toHaveBeenCalled();
  });

  it("does not re-render when the same states are passed again", async () => {
    const hass = hassWith(RIDING);
    const { card, render } = await counted(hass);
    await update(card, { ...hass });
    expect(render).not.toHaveBeenCalled();
  });

  it("re-renders for a watched entity", async () => {
    const hass = hassWith(RIDING);
    const { card, render } = await counted(hass);
    await update(card, withStates(hass, sensor("output_current", "190")));
    expect(render).toHaveBeenCalledTimes(1);
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toBe(
      "Output: 190 W, Avg 150 W, Max 301 W",
    );
  });

  it.each([
    ["the locale", (hass: HomeAssistant) => ({ ...hass, locale: { language: "en" } })],
    ["the language", (hass: HomeAssistant) => ({ ...hass, language: "de" })],
    ["the entity registry", (hass: HomeAssistant) => ({ ...hass, entities: { ...hass.entities } })],
    ["the device registry", (hass: HomeAssistant) => ({ ...hass, devices: { ...hass.devices } })],
    ["the themes", (hass: HomeAssistant) => ({ ...hass, themes: {} })],
    [
      "a formatter",
      (hass: HomeAssistant) => ({
        ...hass,
        formatEntityState: (state: HassEntity) => state.state,
      }),
    ],
  ])("re-renders when %s changes", async (_name, change) => {
    const hass = hassWith(RIDING);
    const { card, render } = await counted(hass);
    await update(card, change(hass));
    expect(render).toHaveBeenCalledTimes(1);
  });

  it("re-renders when the first data arrives for a metric it does not show", async () => {
    const hass = hassWith({ states: { workout: "on", start_time: START }, workout: CYCLING });
    const { card, render } = await counted(hass, {
      metrics: ["heart_rate"],
      show_totals: false,
      show_leaderboard: false,
    });
    expect(find(card, ".hint")).not.toBeNull();
    await update(card, withStates(hass, sensor("output_average", "150")));
    expect(render).toHaveBeenCalledTimes(1);
    expect(find(card, ".hint")).toBeNull();
  });

  it("re-renders for a config change", async () => {
    const { card, render } = await counted(hassWith(RIDING));
    card.setConfig({ type: `custom:${CARD_TYPE}`, variant: "compact" });
    await card.updateComplete;
    expect(render).toHaveBeenCalledTimes(1);
    expect(find(card, ".row")).not.toBeNull();
  });

  it("does not re-render for state changes while there is no device", async () => {
    const hass = makeHass({ riders: [] });
    const { card, render } = await counted(hass);
    await update(card, { ...hass, states: { ...hass.states } });
    expect(render).not.toHaveBeenCalled();
  });

  it("keeps the last render while disconnected", async () => {
    const hass = hassWith(RIDING);
    const { card, render } = await counted(hass);
    const offline = { ...withStates(hass, sensor("output_current", "0")), connected: false };
    await update(card, offline);
    expect(render).not.toHaveBeenCalled();
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toContain("Output: 182 W");

    await update(card, { ...offline, connected: true });
    expect(render).toHaveBeenCalledTimes(1);
    expect(all(card, "button.tile")[0].getAttribute("aria-label")).toContain("Output: 0 W");
  });

  it("does not render before setConfig", async () => {
    const card = document.createElement(CARD_TYPE) as Card;
    card.hass = hassWith(RIDING);
    document.body.append(card);
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector("ha-card") ?? null).toBeNull();
  });

  it("keeps focus on a tile across an update", async () => {
    const hass = hassWith(RIDING);
    const card = await mount(hass);
    const tile = all(card, "button.tile")[1];
    tile.focus();
    expect(root(card).activeElement).toBe(tile);

    await update(card, withStates(hass, sensor("cadence_current", "92")));
    const after = all(card, "button.tile")[1];
    expect(after).toBe(tile);
    expect(root(card).activeElement).toBe(tile);
    expect(tile.getAttribute("aria-label")).toBe("Cadence: 92 rpm, Avg 80 rpm, Max 110 rpm");
  });

  it("keeps the image element across an update", async () => {
    const hass = hassWith(RIDING);
    const card = await mount(hass);
    const image = find(card, ".image img");
    await update(card, withStates(hass, sensor("output_current", "190")));
    expect(find(card, ".image img")).toBe(image);
  });
});

describe("actions", () => {
  it("fires hass-action from the header on click, Enter and Space", async () => {
    const actions = events("hass-action");
    const card = await mount(hassWith(RIDING));
    const header = find(card, ".header");
    header?.click();
    header?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    const space = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    header?.dispatchEvent(space);
    header?.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
    expect(space.defaultPrevented).toBe(true);
    expect(actions).toHaveLength(3);
    for (const ev of actions) {
      expect(ev.bubbles).toBe(true);
      expect(ev.composed).toBe(true);
      expect(ev.detail).toEqual({
        config: { entity: entityIdOf("workout"), tap_action: { action: "more-info" } },
        action: "tap",
      });
    }
  });

  it("passes the configured tap_action", async () => {
    const actions = events("hass-action");
    const tapAction = { action: "navigate", navigation_path: "/lovelace/peloton" };
    const card = await mount(hassWith(FINISHED), { tap_action: tapAction });
    find(card, ".header")?.click();
    expect(actions[0].detail.config).toEqual({
      entity: entityIdOf("workout"),
      tap_action: tapAction,
    });
  });

  it("fires hass-action from the compact row", async () => {
    const actions = events("hass-action");
    const card = await mount(hassWith(RIDING), { variant: "compact" });
    const row = find(card, ".row");
    row?.click();
    row?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(actions).toHaveLength(2);
    expect(actions[0].detail.config.entity).toBe(entityIdOf("workout"));
  });

  it("fires no action in the problem and loading phases", async () => {
    const actions = events("hass-action");
    const problem = await mount(makeHass({ riders: [] }), { variant: "compact" });
    const row = find(problem, ".row");
    row?.click();
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    row?.dispatchEvent(enter);
    const loading = await mount(undefined, { variant: "compact" });
    find(loading, ".row")?.click();
    expect(actions).toHaveLength(0);
    expect(enter.defaultPrevented).toBe(false);
  });

  it("fires hass-more-info for tiles, totals and the leaderboard", async () => {
    const moreInfo = events("hass-more-info");
    const card = await mount(hassWith(RIDING));
    all(card, "button.tile")[0].click();
    all(card, ".totals button")[1].click();
    find(card, "button.leaderboard")?.click();
    expect(moreInfo.map((ev) => ev.detail)).toEqual([
      { entityId: entityIdOf("output_current") },
      { entityId: entityIdOf("distance") },
      { entityId: entityIdOf("leaderboard_rank") },
    ]);
    for (const ev of moreInfo) {
      expect(ev.bubbles).toBe(true);
      expect(ev.composed).toBe(true);
    }
  });

  it("opens the average sensor from a paused tile", async () => {
    const moreInfo = events("hass-more-info");
    const card = await mount(hassWith(PAUSED));
    all(card, "button.tile")[0].click();
    expect(moreInfo[0].detail).toEqual({ entityId: entityIdOf("output_average") });
  });

  it("does not fire from the header click on a tile", async () => {
    const actions = events("hass-action");
    const card = await mount(hassWith(RIDING));
    all(card, "button.tile")[0].click();
    expect(actions).toHaveLength(0);
  });
});

describe("live region", () => {
  it("announces phase changes only", async () => {
    const idle = hassWith(FINISHED);
    const card = await mount(idle);
    expect(text(liveRegion(card))).toBe("");
    expect(liveRegion(card).getAttribute("aria-live")).toBe("polite");

    const riding = withStates(idle, workoutState("on", CYCLING));
    await update(card, riding);
    expect(text(liveRegion(card))).toBe("Workout started");

    await update(card, withStates(riding, sensor("output_current", "250")));
    expect(text(liveRegion(card))).toBe("Workout started");

    const paused = withStates(riding, workoutState("on", { ...CYCLING, paused: true }));
    await update(card, paused);
    expect(text(liveRegion(card))).toBe("Workout paused");

    await update(card, withStates(paused, workoutState("on", CYCLING)));
    expect(text(liveRegion(card))).toBe("Workout resumed");

    await update(card, withStates(paused, workoutState("off", CYCLING)));
    expect(text(liveRegion(card))).toBe("Workout finished");
  });

  it("stays silent on the first render of an active workout", async () => {
    const card = await mount(hassWith(RIDING));
    expect(text(liveRegion(card))).toBe("");
  });

  it("does not announce a reconnect as a new workout", async () => {
    const riding = hassWith(RIDING);
    const card = await mount(riding);
    await update(card, withStates(riding, workoutState("unavailable", {})));
    await update(card, riding);
    expect(text(liveRegion(card))).toBe("");
  });

  it("fades between phases unless reduced motion is requested", async () => {
    const animate = vi.fn();
    const proto = HTMLElement.prototype as HTMLElement & { animate?: unknown };
    const original = proto.animate;
    proto.animate = animate;
    try {
      const idle = hassWith(FINISHED);
      const card = await mount(idle);
      expect(animate).not.toHaveBeenCalled();
      await update(card, withStates(idle, workoutState("on", CYCLING)));
      expect(animate).toHaveBeenCalledTimes(1);

      vi.stubGlobal("matchMedia", () => ({ matches: true }));
      await update(card, withStates(idle, workoutState("off", CYCLING)));
      expect(animate).toHaveBeenCalledTimes(1);
    } finally {
      proto.animate = original;
      vi.unstubAllGlobals();
    }
  });
});

describe("failure containment", () => {
  it("falls back to the unavailable template and warns once", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const broken = new Proxy(
      {},
      {
        get() {
          throw new Error("broken hass");
        },
      },
    ) as HomeAssistant;
    const card = await mount(broken, { name: "Jane" });
    expect(text(find(card, ".title"))).toBe("Jane");
    expect(text(find(card, ".chip"))).toBe("Unavailable");
    expect(find(card, '[role="button"]')).toBeNull();

    card.hass = new Proxy({}, { get: () => 1 }) as unknown as HomeAssistant;
    card.requestUpdate();
    await card.updateComplete;
    card.setConfig({ type: `custom:${CARD_TYPE}`, variant: "compact" });
    card.hass = broken;
    await card.updateComplete;
    expect(text(find(card, ".status"))).toBe("Unavailable");
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("writes nothing to the console in normal operation", async () => {
    const warn = vi.spyOn(console, "warn");
    const error = vi.spyOn(console, "error");
    const log = vi.spyOn(console, "log");
    const idle = hassWith(FINISHED);
    const card = await mount(idle);
    await update(card, withStates(idle, workoutState("on", CYCLING)));
    await update(card, withStates(idle, workoutState("unavailable", {})));
    await mount(makeHass({ riders: [] }), { variant: "compact" });
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });

  it("rejects an invalid config in setConfig", () => {
    const card = document.createElement(CARD_TYPE) as Card;
    expect(() => card.setConfig({ variant: "large" })).toThrow(/variant/);
  });
});

describe("layout and static methods", () => {
  it("reflects the layout set by Home Assistant", async () => {
    const card = await mount(hassWith(RIDING));
    card.layout = "panel";
    await card.updateComplete;
    expect(card.getAttribute("layout")).toBe("panel");
  });

  it("returns grid options per variant", () => {
    const card = document.createElement(CARD_TYPE) as Card;
    expect(card.getGridOptions()).toEqual({
      columns: 12,
      rows: "auto",
      min_columns: 6,
      min_rows: 3,
    });
    card.setConfig({ type: `custom:${CARD_TYPE}`, variant: "compact" });
    expect(card.getGridOptions()).toEqual({ columns: 6, rows: 1, min_columns: 3, max_rows: 2 });
  });

  it("returns the card size per config", async () => {
    const card = document.createElement(CARD_TYPE) as Card;
    expect(card.getCardSize()).toBe(3);
    card.setConfig({ type: `custom:${CARD_TYPE}`, show_totals: false });
    expect(card.getCardSize()).toBe(2);
    card.setConfig({ type: `custom:${CARD_TYPE}` });
    card.hass = hassWith(RIDING);
    expect(card.getCardSize()).toBe(5);

    const mounted = await mount(hassWith(RIDING), {
      metrics: ["output", "cadence", "resistance", "heart_rate", "speed"],
    });
    expect(mounted.getCardSize()).toBe(7);
    const compact = await mount(hassWith(RIDING), { variant: "compact" });
    expect(compact.getCardSize()).toBe(1);
  });

  it("returns a card size for a broken hass", () => {
    const card = document.createElement(CARD_TYPE) as Card;
    card.setConfig({ type: `custom:${CARD_TYPE}` });
    card.hass = new Proxy(
      {},
      {
        get() {
          throw new Error("broken hass");
        },
      },
    ) as HomeAssistant;
    expect(card.getCardSize()).toBe(3);
  });

  it.each([
    ["no device", () => makeHass({ riders: [] }), {}],
    ["one device", () => hassWith(), { device_id: "device-1" }],
    [
      "two devices",
      () =>
        makeHass({
          riders: [rider(), rider({ deviceId: "device-2", prefix: "john_on_peloton" })],
        }),
      {},
    ],
    [
      "one enabled and one disabled device",
      () =>
        makeHass({
          riders: [
            rider(),
            rider({ deviceId: "device-2", prefix: "john_on_peloton", disabled: true }),
          ],
        }),
      { device_id: "device-1" },
    ],
    ["null registries", () => ({ states: {}, entities: null, devices: null }), {}],
  ])("returns a stub config with %s", (_name, hass, expected) => {
    expect(PelotonWorkoutCard.getStubConfig(hass())).toEqual({ variant: "full", ...expected });
  });

  it("suggests the card for the workout sensor only", () => {
    const hass = hassWith();
    expect(entitySuggestion(hass, entityIdOf("workout"))).toEqual({
      config: { type: `custom:${CARD_TYPE}`, device_id: "device-1" },
    });
    expect(entitySuggestion(hass, entityIdOf("output_current"))).toBeNull();
    expect(entitySuggestion(hass, "light.kitchen")).toBeNull();
  });

  it("returns the config form", () => {
    const form = PelotonWorkoutCard.getConfigForm();
    expect(form.schema.map((item) => item.name)).toEqual([
      "device_id",
      "name",
      "variant",
      "metrics",
      "content",
      "tap_action",
    ]);
    const content = form.schema.find((item) => item.name === "content");
    expect(content?.type).toBe("expandable");
    expect(content?.flatten).toBe(true);
    expect(content?.schema?.map((item) => item.name)).toEqual([
      "show_image",
      "show_logo",
      "show_totals",
      "show_leaderboard",
    ]);
    expect(form.schema[0].selector).toEqual({ device: { filter: { integration: "peloton" } } });
    expect(form.computeLabel({ name: "metrics" })).toBe("Metrics");
    expect(form.computeHelper({ name: "device_id" })).toBe("Card version dev");
    expect(() => form.assertConfig({ variant: "large" })).toThrow();
    expect(() => form.assertConfig({ variant: "compact" })).not.toThrow();
  });
});
