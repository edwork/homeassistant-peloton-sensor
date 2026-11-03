// Entry point: defines the card element and adds it to the card picker.
//
// Home Assistant 2026.3 to 2026.10 can run this module before the frontend
// has installed its scoped custom element registry polyfill. A define made
// then lands in the native registry, which the polyfilled registry does not
// see. So the elements are defined at once, and again after <home-assistant>
// is defined, when the polyfill is in place; the polyfill tolerates a tag
// that is already defined natively. Each define uses a new subclass, because
// a constructor can be defined only once. From 2026.11 the frontend sets
// __haScopedRegistryReady and loads this module after the polyfill, so one
// define is enough.
import { CARD_TYPE } from "./config";
import { entitySuggestion } from "./resolve";
import { PelotonWorkoutCard } from "./workout-card";

/** An entry of window.customCards, read by the card picker. */
export interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview: boolean;
  documentationURL: string;
  getEntitySuggestion: typeof entitySuggestion;
}

declare global {
  interface Window {
    customCards?: { type: string }[];
    __haScopedRegistryReady?: boolean;
  }
}

export const CARD_ENTRY: CustomCardEntry = {
  type: CARD_TYPE,
  name: "Peloton workout",
  description: "Live and last Peloton workout",
  preview: true,
  documentationURL: "https://github.com/edwork/homeassistant-peloton-sensor#workout-card",
  getEntitySuggestion: entitySuggestion,
};

const ELEMENTS: [string, typeof PelotonWorkoutCard][] = [[CARD_TYPE, PelotonWorkoutCard]];

// Wait up to 60 s for <home-assistant>, in steps of 100 ms.
const WAIT_STEPS = 600;
const WAIT_STEP_MS = 100;

function defineAll(): void {
  for (const [tag, cls] of ELEMENTS) {
    if (window.customElements.get(tag)) continue;
    try {
      window.customElements.define(tag, class extends cls {});
    } catch (err) {
      console.warn("peloton-cards: could not define", tag, err);
    }
  }
}

function registerCard(): void {
  window.customCards ??= [];
  if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
    window.customCards.push(CARD_ENTRY);
  }
}

defineAll();
registerCard();
if (!window.__haScopedRegistryReady) {
  void (async () => {
    for (let i = 0; i < WAIT_STEPS && !window.customElements.get("home-assistant"); i++) {
      await new Promise((resolve) => setTimeout(resolve, WAIT_STEP_MS));
    }
    defineAll();
  })();
}
