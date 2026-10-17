"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { type DayKey, type Lang, type MessageKey, messages } from "./messages";

const STORAGE_KEY = "showcase.lang";

type I18n = { lang: Lang; setLang: (l: Lang) => void; t: (k: MessageKey) => string; day: (d: string) => string };
const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("hi");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
      if (saved && saved in messages) setLangState(saved);
    } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {}
  }, []);

  const t = useCallback((k: MessageKey) => messages[lang][k] ?? messages.en[k], [lang]);
  const day = useCallback((d: string) => messages[lang].days[d as DayKey] ?? d, [lang]);
  return <Ctx.Provider value={{ lang, setLang, t, day }}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
