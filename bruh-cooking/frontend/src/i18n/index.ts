/**
 * Panel text in the integration's nine languages: one flat table of dotted keys per language,
 * with placeholders like {name}. English fills any key a language lacks; test/i18n.test.ts
 * checks every language has exactly the English keys and placeholders.
 */
import de from "./de.json";
import en from "./en.json";
import es from "./es.json";
import fr from "./fr.json";
import it from "./it.json";
import nl from "./nl.json";
import pl from "./pl.json";
import sv from "./sv.json";
import zhHans from "./zh-Hans.json";

export const LANGUAGES = ["en", "de", "es", "fr", "it", "nl", "pl", "sv", "zh-Hans"] as const;
export type Language = (typeof LANGUAGES)[number];

type Table = Record<string, string>;

export const TABLES: Record<Language, Table> = {
  en,
  de,
  es,
  fr,
  it,
  nl,
  pl,
  sv,
  "zh-Hans": zhHans,
};

export type Translate = (key: string, vars?: Record<string, string | number>) => string;

/**
 * The panel language for a Home Assistant language tag: a regional variant uses its base
 * ("de-CH" is "de"), any Chinese uses Simplified (the only Chinese the integration ships),
 * and anything else English.
 */
export function resolveLanguage(language: string | undefined): Language {
  if (!language) return "en";
  if ((LANGUAGES as readonly string[]).includes(language)) return language as Language;
  const base = language.split(/[-_]/)[0].toLowerCase();
  if (base === "zh") return "zh-Hans";
  return (LANGUAGES as readonly string[]).includes(base) ? (base as Language) : "en";
}

export function makeTranslate(language: string | undefined): Translate {
  const lang = resolveLanguage(language);
  const table: Table = { ...TABLES.en, ...TABLES[lang] };
  return (key, vars) => {
    const text = table[key] ?? key;
    return vars ? text.replace(/\{(\w+)\}/g, (match, name) => String(vars[name] ?? match)) : text;
  };
}
