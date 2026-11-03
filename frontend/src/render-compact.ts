// Template of the compact variant: one row with the icon, the name and the status.
import { html, nothing, type TemplateResult } from "lit";
import { ifDefined } from "lit/directives/if-defined.js";
import { iconTemplate, type RenderContext } from "./render-full";
import type { CardView } from "./types";

/** The content of the compact variant for one view. */
export function renderCompact(view: CardView, ctx: RenderContext): TemplateResult {
  if (view.phase === "loading") return html`<div class="row"></div>`;
  const name = view.header?.name;
  const { text, tone, icon } = view.compact;
  const label = name ? `${name}: ${text}` : text;
  const action = view.action !== null;
  // Long text ends in an ellipsis, so the full text also goes into the title.
  return html`<div
    class="row"
    role=${ifDefined(action ? "button" : undefined)}
    tabindex=${ifDefined(action ? "0" : undefined)}
    title=${label}
    aria-label=${ifDefined(action ? label : undefined)}
    @click=${ctx.onAction}
    @keydown=${ctx.onActionKey}
  >
    ${iconTemplate(icon, tone, true)}
    ${name ? html`<span class="name">${name}</span>` : nothing}
    <span class="status">${text}</span>
  </div>`;
}
