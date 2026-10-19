// UI strings live in lib/locales/<code>.ts. English is the default (SPEC §8).
// To add a language: create lib/locales/<code>.ts typed as `Messages` (the build fails if any key is missing),
// register it below, and allow the code in backend/app/schemas/customer.py (LANGUAGES).
import bn from "./locales/bn";
import en from "./locales/en";
import gu from "./locales/gu";
import hi from "./locales/hi";
import kn from "./locales/kn";
import mr from "./locales/mr";
import or from "./locales/or";
import te from "./locales/te";

export const messages = { en, hi, bn, te, mr, gu, kn, or };

export type Lang = keyof typeof messages;
export type MessageKey = Exclude<keyof typeof en, "days">;
export type DayKey = keyof typeof en.days;
export const DEFAULT_LANG: Lang = "en";

/** Shown in each language's own script so people can find theirs. */
export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "bn", label: "বাংলা" },
  { code: "te", label: "తెలుగు" },
  { code: "mr", label: "मराठी" },
  { code: "gu", label: "ગુજરાતી" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "or", label: "ଓଡ଼ିଆ" },
];

/**
 * Locale for dates/numbers, e.g. "gu-IN-u-nu-latn". Digits are always 0-9 so a date and an amount on the same
 * row use one digit style (deep audit). If the browser has no data for the language (e.g. Odia in Chromium),
 * fall back to "en-IN" rather than silently getting US English.
 */
export function intlLocale(lang: Lang): string {
  const wanted = `${lang}-IN-u-nu-latn`;
  try {
    const got = new Intl.DateTimeFormat(wanted).resolvedOptions().locale;
    return got.startsWith(lang) ? wanted : "en-IN";
  } catch {
    return "en-IN";
  }
}
