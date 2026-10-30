import { describe, expect, it } from "vitest";
import { LANGUAGES, makeTranslate, resolveLanguage, TABLES } from "../src/i18n";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

describe("languages", () => {
  it.each(LANGUAGES.filter((language) => language !== "en"))("%s has exactly the English keys and placeholders", (language) => {
    const english = TABLES.en;
    const table = TABLES[language];
    expect(Object.keys(table).sort()).toEqual(Object.keys(english).sort());
    for (const [key, text] of Object.entries(english)) {
      expect(table[key].trim(), key).not.toBe("");
      expect(placeholders(table[key]), key).toEqual(placeholders(text));
    }
  });

  it("picks the language Home Assistant uses", () => {
    expect(resolveLanguage("de-CH")).toBe("de");
    expect(resolveLanguage("zh-Hant")).toBe("zh-Hans");
    expect(resolveLanguage("pt-BR")).toBe("en");
    expect(makeTranslate("en")("status.preheating_pct", { n: 40 })).toBe("Preheating 40%");
    expect(makeTranslate("en")("no.such.key")).toBe("no.such.key");
  });
});
