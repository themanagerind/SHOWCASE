"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { clearTokens, isLoggedIn } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function Header() {
  const { lang, setLang, t } = useI18n();
  const [loggedIn, setLoggedIn] = useState(false);
  const pathname = usePathname();
  // Re-check on every navigation: login happens via client-side routing.
  useEffect(() => setLoggedIn(isLoggedIn()), [pathname]);

  return (
    <header className="header">
      <Link href="/" className="brand">{t("appName")}</Link>
      <nav>
        {loggedIn ? (
          <>
            <Link href="/favourites">{t("favourites").split(" ").slice(-2).join(" ")}</Link>
            <Link href="/profile">{t("profile")}</Link>
            <button className="lang-toggle" onClick={() => { clearTokens(); location.href = "/"; }}>{t("logout")}</button>
          </>
        ) : (
          <Link href="/login">{t("login")}</Link>
        )}
        <button className="lang-toggle" onClick={() => setLang(lang === "hi" ? "en" : "hi")} aria-label="Language">
          {lang === "hi" ? "EN" : "हिं"}
        </button>
      </nav>
    </header>
  );
}
