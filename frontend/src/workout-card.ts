// The Peloton workout card element. Static properties and declare fields
// instead of decorators: Lit's dev build throws on shadowing class fields.
import { html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { DEFAULTS, getConfigForm, validateConfig } from "./config";
import { DEFAULT_ICON } from "./format";
import { localize } from "./localize";
import { renderCompact } from "./render-compact";
import { type RenderContext, renderFull } from "./render-full";
import { resolve, stubConfig } from "./resolve";
import { styles } from "./styles";
import type { CardConfig, CardView, HomeAssistant, Phase } from "./types";
import { announcement, cardSize, computeView, gridOptions } from "./view";

// Parts of hass whose change can change any text on the card.
const HASS_KEYS = [
  "entities",
  "devices",
  "locale",
  "language",
  "themes",
  "connected",
  "formatEntityState",
  "formatEntityStateToParts",
  "formatEntityAttributeValue",
] as const;

/** The view shown when computing or rendering the real one failed. */
function fallbackView(hass: unknown, config: CardConfig): CardView {
  return {
    phase: "unavailable",
    variant: config.variant,
    problem: null,
    header: {
      name: config.name ?? "Peloton",
      icon: null,
      title: null,
      classLine: null,
      timeLine: null,
      chip: { text: localize(hass, "chip.unavailable"), tone: "unavailable" },
    },
    message: localize(hass, "message.unavailable"),
    detail: null,
    tiles: [],
    tilesMuted: false,
    hint: null,
    totals: [],
    leaderboard: null,
    leaderboardEntityId: null,
    image: null,
    logo: config.variant === "full" && config.show_logo,
    compact: {
      icon: DEFAULT_ICON,
      tone: "unavailable",
      text: localize(hass, "compact.unavailable"),
    },
    action: null,
    announce: null,
    watched: [],
  };
}

function fire(node: HTMLElement, type: string, detail: unknown): void {
  node.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
}

function reducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export class PelotonWorkoutCard extends LitElement {
  static override properties = {
    hass: { attribute: false },
    // Set by Home Assistant: "grid" in sections, "panel" in a panel view.
    layout: { reflect: true },
    _config: { state: true },
    _imageFailed: { state: true },
  };

  static override styles = styles;

  declare hass?: HomeAssistant;
  declare layout?: string;
  declare protected _config?: CardConfig;
  declare protected _imageFailed?: string;

  private _view?: CardView;
  private _phase?: Phase;
  private _phaseChanged = false;
  private _announce = "";
  private _warned = false;

  static getConfigForm() {
    return getConfigForm();
  }

  static getStubConfig(hass: unknown): { device_id?: string } {
    return stubConfig(hass);
  }

  setConfig(config: unknown): void {
    this._config = validateConfig(config);
  }

  getCardSize(): number {
    const config = this._config ?? DEFAULTS;
    try {
      return cardSize(config, this._view ?? computeView(this.hass, config));
    } catch {
      return cardSize(config, undefined);
    }
  }

  getGridOptions(): Readonly<Record<string, unknown>> {
    return gridOptions(this._config ?? DEFAULTS);
  }

  protected override shouldUpdate(changed: PropertyValues<this>): boolean {
    const config = this._config;
    if (!config) return false;
    if (changed.size !== 1 || !changed.has("hass")) return true;
    const oldHass = changed.get("hass") as HomeAssistant | undefined;
    const hass = this.hass;
    if (!oldHass || !hass) return true;
    try {
      // Home Assistant shows its own banner; keep the last render meanwhile.
      if (hass.connected === false && this.hasUpdated) return false;
      if (HASS_KEYS.some((key) => oldHass[key] !== hass[key])) return true;
      const resolution = resolve(hass, config);
      if (resolution.status !== "ok") return false;
      const { states } = hass;
      const oldStates = oldHass.states;
      if (states === oldStates) return false;
      return resolution.watched.some((id) => oldStates?.[id] !== states?.[id]);
    } catch {
      return true;
    }
  }

  protected override render(): TemplateResult | typeof nothing {
    const config = this._config;
    if (!config) return nothing;
    let view: CardView;
    let content: TemplateResult;
    try {
      view = computeView(this.hass, config);
      content = this._content(view, this.hass);
    } catch (err) {
      if (!this._warned) {
        this._warned = true;
        console.warn("peloton-workout-card: could not render the card", err);
      }
      // English strings without hass, which may be what failed.
      view = fallbackView(undefined, config);
      content = this._content(view, undefined);
    }
    this._view = view;
    this._track(view.phase);
    const classes = [view.variant, view.phase === "problem" ? "problem" : ""].join(" ");
    return html`<ha-card class=${classes}>
      <div class="root">
        ${content}
        <div class="sr-only" role="status" aria-live="polite" aria-atomic="true">
          ${this._announce}
        </div>
      </div>
    </ha-card>`;
  }

  protected override updated(changed: PropertyValues<this>): void {
    super.updated(changed);
    if (!this._phaseChanged) return;
    this._phaseChanged = false;
    const root = this.renderRoot.querySelector(".root");
    if (root && typeof root.animate === "function" && !reducedMotion()) {
      root.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 150, easing: "ease-out" });
    }
  }

  private _content(view: CardView, hass: unknown): TemplateResult {
    const ctx: RenderContext = {
      onAction: this._onAction,
      onActionKey: this._onActionKey,
      onMoreInfo: this._onMoreInfo,
      onImageError: this._onImageError,
      imageFailed: this._imageFailed,
      noValue: localize(hass, "value.none"),
    };
    return view.variant === "compact" ? renderCompact(view, ctx) : renderFull(view, ctx);
  }

  /** Remember the phase and set the live region text on a phase change. */
  private _track(phase: Phase): void {
    const previous = this._phase;
    this._phase = phase;
    if (previous === undefined || previous === phase) return;
    this._phaseChanged = true;
    let text: string | null;
    try {
      text = announcement(this.hass, previous, phase);
    } catch {
      text = announcement(undefined, previous, phase);
    }
    if (text !== null) this._announce = text;
  }

  private _onAction = (): void => {
    const action = this._view?.action;
    if (!action) return;
    fire(this, "hass-action", {
      config: { entity: action.entity, tap_action: action.tap_action },
      action: "tap",
    });
  };

  private _onActionKey = (ev: KeyboardEvent): void => {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    if (!this._view?.action) return;
    ev.preventDefault();
    this._onAction();
  };

  private _onMoreInfo = (ev: Event): void => {
    const target = ev.currentTarget as HTMLElement | null;
    const entityId = target?.dataset.entity;
    if (entityId) fire(this, "hass-more-info", { entityId });
  };

  private _onImageError = (ev: Event): void => {
    const target = ev.currentTarget as HTMLImageElement | null;
    this._imageFailed = target?.getAttribute("src") ?? undefined;
  };
}
