// Styles of the workout card. Only theme variables with literal fallbacks;
// the card's own variables can be set from a theme or card-mod.
import { css } from "lit";

export const styles = css`
  :host {
    display: block;
    /* Card variables: a theme or card-mod may set the --peloton-* names. */
    --_active: var(
      --peloton-active-color,
      var(--state-binary_sensor-active-color, var(--amber-color, #ffc107))
    );
    --_paused: var(--peloton-paused-color, var(--warning-color, #ffa600));
    --_idle: var(--peloton-idle-color, var(--secondary-text-color, #727272));
    --_unavailable: var(--state-unavailable-color, #bdbdbd);
    --_warning: var(--warning-color, #ffa600);
    /* Peloton Red, from the integration's icon. */
    --_brand: var(--peloton-accent-color, #df1c2f);
    --_space-2: var(--ha-space-2, 8px);
    --_space-4: var(--ha-space-4, 16px);
    --_secondary: var(--secondary-text-color, #727272);
  }

  /* The same surface as ha-card, so the card reads correctly without it. */
  ha-card {
    display: block;
    box-sizing: border-box;
    height: 100%;
    overflow: hidden;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    border-width: var(--ha-card-border-width, 1px);
    border-style: solid;
    border-color: var(--peloton-border-color, var(--_brand));
    color: var(--primary-text-color, #212121);
  }

  ha-card.problem {
    border-color: var(--_warning);
  }

  .root {
    container-type: inline-size;
    box-sizing: border-box;
    height: 100%;
    padding: var(--_space-4);
  }

  .compact .root {
    display: flex;
    align-items: center;
    padding: var(--_space-2) var(--_space-4);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
    border: 0;
  }

  .tone-active {
    --_tone: var(--_active);
  }
  .tone-paused {
    --_tone: var(--_paused);
  }
  .tone-idle {
    --_tone: var(--_idle);
  }
  .tone-unavailable {
    --_tone: var(--_unavailable);
  }
  .tone-warning {
    --_tone: var(--_warning);
  }
  .tone-none {
    --_tone: var(--_idle);
  }

  [role="button"],
  button {
    cursor: pointer;
    border-radius: 8px;
  }

  [role="button"]:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }

  button {
    display: block;
    box-sizing: border-box;
    min-width: 0;
    margin: 0;
    padding: var(--_space-2);
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
  }

  dl,
  dd {
    margin: 0;
  }

  .loading {
    min-height: 120px;
  }

  .icon-box {
    display: flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    color: var(--_tone, var(--_idle));
    --mdc-icon-size: 24px;
  }

  .logo {
    flex: none;
    box-sizing: border-box;
    width: 40px;
    height: 40px;
    padding: 2px;
    fill: var(--_brand);
  }

  .problem-body {
    display: flex;
    align-items: center;
    gap: var(--_space-2);
  }

  .problem-body .icon-box {
    color: var(--_warning);
  }

  .problem-body p {
    margin: 0;
  }

  /* Header */
  .header-row {
    display: flex;
    align-items: flex-start;
    gap: var(--_space-4);
  }

  .header {
    display: flex;
    flex: 1;
    align-items: flex-start;
    gap: var(--_space-2);
    min-width: 0;
    padding: var(--_space-2);
    margin: calc(var(--_space-2) * -1);
  }

  .heading {
    flex: 1;
    min-width: 0;
  }

  .name {
    overflow: hidden;
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .title-line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--_space-2);
  }

  .title {
    display: -webkit-box;
    overflow: hidden;
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 1.3;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow-wrap: anywhere;
  }

  .chip {
    flex: none;
    padding: 2px var(--_space-2);
    border-radius: 999px;
    background: color-mix(in srgb, var(--_tone) 20%, transparent);
    color: var(--primary-text-color, #212121);
    font-size: var(--ha-font-size-s, 12px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 1.5;
    white-space: nowrap;
  }

  .chip.tone-unavailable {
    color: var(--_idle);
  }

  .class-line {
    margin-top: 2px;
    overflow: hidden;
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .image {
    display: none;
    flex: none;
    width: 160px;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: 8px;
    background: var(--secondary-background-color, #e5e5e5);
  }

  .image img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  /* Body */
  .message {
    margin: var(--_space-4) 0 0;
    color: var(--_secondary);
  }

  .hint {
    margin: var(--_space-2) 0 0;
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--_space-2);
    margin-top: var(--_space-4);
  }

  :host([layout="panel"]) .tiles {
    max-width: 960px;
  }

  .tile dt,
  .stat dt {
    overflow: hidden;
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tile .main {
    overflow: hidden;
    font-size: clamp(1.5rem, 6cqi, 2.5rem);
    font-weight: var(--ha-font-weight-medium, 500);
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .muted .main {
    color: var(--_secondary);
  }

  .value-label,
  .unit {
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-normal, 400);
  }

  .value-label {
    color: var(--_secondary);
  }

  .tile .secondary {
    overflow: hidden;
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    font-variant-numeric: tabular-nums;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .footer {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--_space-2);
    margin-top: var(--_space-4);
    padding-top: var(--_space-2);
    border-top: 1px solid var(--divider-color, #e0e0e0);
  }

  .totals {
    display: flex;
    flex: 1;
    flex-wrap: wrap;
    gap: var(--_space-2);
    min-width: 0;
  }

  .stat dd {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .leaderboard {
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    font-variant-numeric: tabular-nums;
  }

  /* Compact variant */
  .row {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--_space-2);
    min-width: 0;
    min-height: 40px;
  }

  .ring {
    box-sizing: border-box;
    border: 2px solid var(--_tone);
    border-radius: 50%;
  }

  .row .text {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }

  .row .name {
    color: var(--_secondary);
    font-size: var(--ha-font-size-s, 12px);
    line-height: 1.3;
  }

  .status {
    overflow: hidden;
    color: var(--primary-text-color, #212121);
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    line-height: 1.3;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Columns follow the number of tiles, so no row is left with one tile:
     two tiles side by side, three in a row, four as 2 x 2 or 4 x 1. */
  .tiles.count-1 {
    grid-template-columns: minmax(0, 1fr);
  }

  @container (min-width: 300px) {
    .tiles.count-3,
    .tiles.count-5,
    .tiles.count-6,
    .tiles.count-7 {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }

  /* Content width: the card is 34 px wider (padding and border). */
  @container (min-width: 400px) {
    .image {
      display: block;
    }
  }

  @container (min-width: 480px) {
    .tiles.count-4 {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .tiles:is(.count-1, .count-2, .count-3) .tile.primary .main {
      font-size: clamp(2rem, 8cqi, 3.5rem);
    }
  }

  @container (min-width: 600px) {
    .tiles.count-7 {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
  }
`;
