// The card's own strings. A custom card cannot add frontend translation keys,
// so the strings ship in the bundle as flat key maps per language.
import en from "./translations/en.json";

export type Strings = Readonly<Record<string, string>>;

export const TRANSLATIONS: Readonly<Record<string, Strings>> = { en };

/** Language of the user: hass.locale.language, else hass.language. */
export function language(hass: unknown): string | undefined {
  if (typeof hass !== "object" || hass === null) return undefined;
  const { locale, language: lang } = hass as { locale?: unknown; language?: unknown };
  if (typeof locale === "object" && locale !== null) {
    const value = (locale as { language?: unknown }).language;
    if (typeof value === "string" && value) return value;
  }
  return typeof lang === "string" && lang ? lang : undefined;
}

function lookup(lang: string | undefined, key: string): string | undefined {
  const candidates: string[] = [];
  if (lang) {
    candidates.push(lang);
    const base = lang.split(/[-_]/)[0];
    if (base && base !== lang) candidates.push(base);
  }
  candidates.push("en");
  for (const candidate of candidates) {
    const strings = Object.hasOwn(TRANSLATIONS, candidate) ? TRANSLATIONS[candidate] : undefined;
    if (strings && Object.hasOwn(strings, key)) return strings[key];
  }
  return undefined;
}

/**
 * Return the string for `key` in the user's language, then its base
 * language, then English, then the key itself. `{name}` placeholders are
 * replaced from `vars`; unknown placeholders are kept.
 */
export function localize(
  hass: unknown,
  key: string,
  vars?: Readonly<Record<string, string | number>>,
): string {
  const text = lookup(language(hass), key) ?? key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : match,
  );
}
