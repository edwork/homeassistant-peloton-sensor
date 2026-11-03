import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CARD_TYPE } from "../src/config";
import { hassWith } from "./fake-hass";

/**
 * A stand-in for the frontend's registries on 2026.3 to 2026.10: defines go
 * to the native registry until the scoped registry polyfill is installed,
 * after which get() and define() only see the polyfilled registry.
 */
class FakeRegistry {
  readonly native = new Map<string, CustomElementConstructor>();
  scoped: Map<string, CustomElementConstructor> | null = null;
  readonly defines: [string, CustomElementConstructor][] = [];
  failing = false;

  get(tag: string): CustomElementConstructor | undefined {
    return (this.scoped ?? this.native).get(tag);
  }

  define(tag: string, cls: CustomElementConstructor): void {
    this.defines.push([tag, cls]);
    if (this.failing) throw new Error("define failed");
    const registry = this.scoped ?? this.native;
    if (registry.has(tag)) throw new Error(`${tag} is already defined`);
    registry.set(tag, cls);
  }

  /** Install the polyfill, then define <home-assistant>, as the app does. */
  startApp(): void {
    this.scoped = new Map();
    this.define("home-assistant", class extends HTMLElement {});
  }

  definesOf(tag: string): CustomElementConstructor[] {
    return this.defines.filter(([name]) => name === tag).map(([, cls]) => cls);
  }
}

async function importIndex() {
  return import("../src/index");
}

function useRegistry(registry: FakeRegistry): void {
  Object.defineProperty(window, "customElements", { value: registry, configurable: true });
}

const realRegistry = window.customElements;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  delete window.customCards;
  delete window.__haScopedRegistryReady;
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  Object.defineProperty(window, "customElements", { value: realRegistry, configurable: true });
});

describe("registration", () => {
  it("defines the card and adds one picker entry when imported twice", async () => {
    const warn = vi.spyOn(console, "warn");
    await importIndex();
    vi.resetModules();
    const { CARD_ENTRY } = await importIndex();
    await vi.advanceTimersByTimeAsync(1000);

    expect(customElements.get(CARD_TYPE)).toBeDefined();
    // The entry of the first import stays; the second import adds none.
    expect(window.customCards).toHaveLength(1);
    expect(window.customCards?.[0]).not.toBe(CARD_ENTRY);
    expect(window.customCards?.[0]).toMatchObject({
      type: CARD_TYPE,
      name: "Peloton workout",
      description: "Live and last Peloton workout",
      preview: true,
      documentationURL: "https://github.com/edwork/homeassistant-peloton-sensor#workout-card",
    });
    // Vitest resolves Lit's development build, which announces itself on import.
    const ours = warn.mock.calls.filter(
      ([message]) => !String(message).startsWith("Lit is in dev mode"),
    );
    expect(ours).toEqual([]);

    const card = document.createElement(CARD_TYPE) as HTMLElement & {
      setConfig(config: unknown): void;
      hass: unknown;
      updateComplete: Promise<boolean>;
    };
    card.setConfig({ type: `custom:${CARD_TYPE}` });
    card.hass = hassWith();
    document.body.append(card);
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector("ha-card")).not.toBeNull();
    card.remove();
  });

  it("keeps the entries of other cards", async () => {
    window.customCards = [{ type: "other-card" }];
    await importIndex();
    expect(window.customCards.map((card) => card.type)).toEqual(["other-card", CARD_TYPE]);
  });

  it("offers the card for a Peloton workout sensor", async () => {
    const { CARD_ENTRY } = await importIndex();
    const hass = hassWith();
    expect(CARD_ENTRY.getEntitySuggestion(hass, "binary_sensor.jane_on_peloton_workout")).toEqual({
      config: { type: `custom:${CARD_TYPE}`, device_id: "device-1" },
    });
    expect(CARD_ENTRY.getEntitySuggestion(hass, "light.kitchen")).toBeNull();
  });

  it("defines again in the polyfilled registry after home-assistant is defined", async () => {
    const registry = new FakeRegistry();
    useRegistry(registry);
    const warn = vi.spyOn(console, "warn");

    await importIndex();
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(1);
    expect(registry.native.has(CARD_TYPE)).toBe(true);

    await vi.advanceTimersByTimeAsync(500);
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(1);

    registry.startApp();
    await vi.advanceTimersByTimeAsync(100);
    const defined = registry.definesOf(CARD_TYPE);
    expect(defined).toHaveLength(2);
    expect(defined[1]).not.toBe(defined[0]);
    expect(registry.scoped?.get(CARD_TYPE)).toBe(defined[1]);
    expect(Object.getPrototypeOf(defined[1])).toBe(Object.getPrototypeOf(defined[0]));
    expect(warn).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(60_000);
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("defines only once when home-assistant is already defined", async () => {
    const registry = new FakeRegistry();
    registry.startApp();
    useRegistry(registry);
    await importIndex();
    await vi.advanceTimersByTimeAsync(0);
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops waiting for home-assistant after 60 seconds", async () => {
    const registry = new FakeRegistry();
    useRegistry(registry);
    await importIndex();
    await vi.advanceTimersByTimeAsync(59_900);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(vi.getTimerCount()).toBe(0);
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(1);
  });

  it("does not wait when the frontend set __haScopedRegistryReady", async () => {
    const registry = new FakeRegistry();
    useRegistry(registry);
    window.__haScopedRegistryReady = true;
    await importIndex();
    expect(registry.definesOf(CARD_TYPE)).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(window.customCards?.map((card) => card.type)).toEqual([CARD_TYPE]);
  });

  it("logs a warning when a define fails", async () => {
    const registry = new FakeRegistry();
    registry.failing = true;
    useRegistry(registry);
    window.__haScopedRegistryReady = true;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await importIndex();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0].slice(0, 2)).toEqual(["peloton-cards: could not define", CARD_TYPE]);
    expect(window.customCards?.map((card) => card.type)).toEqual([CARD_TYPE]);
  });
});
