// Template of the full variant, and the parts shared with the compact one.
// All text goes through Lit text and attribute bindings, so values from
// Peloton (class titles, instructor names, image URLs) are never parsed as HTML.
import { html, nothing, type TemplateResult } from "lit";
import { ifDefined } from "lit/directives/if-defined.js";
import { repeat } from "lit/directives/repeat.js";
import { logoTemplate } from "./logo";
import type { CardView, ChipView, HeaderView, StatView, TileView, ValueView } from "./types";

/** Event handlers and element state the templates need from the card. */
export interface RenderContext {
  /** Header (full) or row (compact) click: fires hass-action. */
  readonly onAction: (ev: Event) => void;
  /** Enter and Space on the header or row. */
  readonly onActionKey: (ev: KeyboardEvent) => void;
  /** Click on an element with data-entity: fires hass-more-info. */
  readonly onMoreInfo: (ev: Event) => void;
  readonly onImageError: (ev: Event) => void;
  /** URL of an image that failed to load; hidden until the URL changes. */
  readonly imageFailed: string | undefined;
  /** Text for unknown values, such as "No value". */
  readonly noValue: string;
}

/** A value with its unit parts at a smaller size; a dash when unknown. */
export function valueTemplate(value: ValueView, ctx: RenderContext): unknown {
  if (!value.known) {
    return html`<span class="dash" aria-hidden="true">${value.text}</span
      ><span class="sr-only">${ctx.noValue}</span>`;
  }
  return value.parts.map((part) =>
    part.type === "unit" ? html`<span class="unit">${part.value}</span>` : part.value,
  );
}

/** A discipline or warning icon in a fixed box, so a missing ha-icon keeps the layout. */
export function iconTemplate(icon: string, tone: string, ring = false): TemplateResult {
  return html`<span class="icon-box tone-${tone}${ring ? " ring" : ""}" aria-hidden="true"
    ><ha-icon icon=${icon}></ha-icon
  ></span>`;
}

function chipTemplate(chip: ChipView | null): unknown {
  return chip ? html`<span class="chip tone-${chip.tone}">${chip.text}</span>` : nothing;
}

function headerTemplate(view: CardView, header: HeaderView, ctx: RenderContext): TemplateResult {
  const action = view.action !== null;
  const tone = header.chip?.tone ?? "none";
  const heading = header.title
    ? html`<div class="name">${header.name}</div>
        <div class="title-line">
          <span class="title">${header.title}</span>${chipTemplate(header.chip)}
        </div>`
    : html`<div class="title-line">
        <span class="title">${header.name}</span>${chipTemplate(header.chip)}
      </div>`;
  const image =
    view.image !== null && view.image !== ctx.imageFailed
      ? html`<div class="image">
          <img
            alt=""
            loading="lazy"
            decoding="async"
            referrerpolicy="no-referrer"
            src=${view.image}
            @error=${ctx.onImageError}
          />
        </div>`
      : nothing;
  return html`<div class="header-row">
    <div
      class="header"
      role=${ifDefined(action ? "button" : undefined)}
      tabindex=${ifDefined(action ? "0" : undefined)}
      @click=${ctx.onAction}
      @keydown=${ctx.onActionKey}
    >
      ${view.logo ? logoTemplate() : header.icon ? iconTemplate(header.icon, tone) : nothing}
      <div class="heading">
        ${heading}
        ${header.classLine ? html`<div class="class-line">${header.classLine}</div>` : nothing}
        ${header.timeLine ? html`<div class="class-line time-line">${header.timeLine}</div>` : nothing}
      </div>
    </div>
    ${image}
  </div>`;
}

/** Accessible name of a tile: "Output: 182 W, Avg 150 W, Max 301 W". */
export function tileLabel(tile: TileView): string {
  const main = tile.valueLabel ? `${tile.valueLabel} ${tile.value.label}` : tile.value.label;
  const items = [main, ...tile.secondary.map((item) => `${item.label} ${item.value.label}`)];
  return `${tile.label}: ${items.join(", ")}`;
}

function tileTemplate(tile: TileView, ctx: RenderContext): TemplateResult {
  const valueLabel = tile.valueLabel
    ? html`<span class="value-label">${tile.valueLabel}</span> `
    : nothing;
  return html`<button
    type="button"
    class=${tile.primary ? "tile primary" : "tile"}
    data-entity=${tile.entityId}
    aria-label=${tileLabel(tile)}
    @click=${ctx.onMoreInfo}
  >
    <dl>
      <dt>${tile.label}</dt>
      <dd class="main">
        ${valueLabel}${valueTemplate(tile.value, ctx)}
      </dd>
      ${tile.secondary.length ? html`<dd class="secondary">${tile.secondaryText}</dd>` : nothing}
    </dl>
  </button>`;
}

function statTemplate(item: StatView, ctx: RenderContext): TemplateResult {
  const content = html`<dl>
    <dt>${item.label}</dt>
    <dd>${valueTemplate(item.value, ctx)}</dd>
  </dl>`;
  if (item.entityId === null) return html`<div class="stat">${content}</div>`;
  return html`<button
    type="button"
    class="stat"
    data-entity=${item.entityId}
    aria-label="${item.label}: ${item.value.label}"
    @click=${ctx.onMoreInfo}
  >
    ${content}
  </button>`;
}

function leaderboardTemplate(view: CardView, ctx: RenderContext): unknown {
  if (view.leaderboard === null) return nothing;
  if (view.leaderboardEntityId === null) {
    return html`<span class="leaderboard">${view.leaderboard}</span>`;
  }
  return html`<button
    type="button"
    class="leaderboard"
    data-entity=${view.leaderboardEntityId}
    @click=${ctx.onMoreInfo}
  >
    ${view.leaderboard}
  </button>`;
}

function footerTemplate(view: CardView, ctx: RenderContext): unknown {
  if (!view.totals.length && view.leaderboard === null) return nothing;
  return html`<div class="footer">
    ${
      view.totals.length
        ? html`<div class="totals">
            ${repeat(
              view.totals,
              (item) => item.key,
              (item) => statTemplate(item, ctx),
            )}
          </div>`
        : nothing
    }
    ${leaderboardTemplate(view, ctx)}
  </div>`;
}

/** The content of the full variant for one view. */
export function renderFull(view: CardView, ctx: RenderContext): TemplateResult {
  if (view.phase === "loading") return html`<div class="loading"></div>`;
  if (view.phase === "problem" || view.header === null) {
    return html`<div class="problem-body">
      ${iconTemplate(view.compact.icon, view.compact.tone)}
      <p class="problem-text">${view.message}</p>
    </div>`;
  }
  return html`${headerTemplate(view, view.header, ctx)}
    ${view.message ? html`<p class="message">${view.message}</p>` : nothing}
    ${view.detail ? html`<div class="footer">${statTemplate(view.detail, ctx)}</div>` : nothing}
    ${view.hint ? html`<p class="hint">${view.hint}</p>` : nothing}
    ${
      view.tiles.length
        ? html`<div
            class="tiles count-${Math.min(view.tiles.length, 7)}${view.tilesMuted ? " muted" : ""}"
          >
            ${repeat(
              view.tiles,
              (tile) => tile.key,
              (tile) => tileTemplate(tile, ctx),
            )}
          </div>`
        : nothing
    }
    ${footerTemplate(view, ctx)}`;
}
