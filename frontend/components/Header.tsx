"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { isLoggedIn } from "@/lib/api";
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
        <Link href="/discover">{t("navDiscover")}</Link>
        {loggedIn ? (
          <>
            <Link href="/favourites">{t("navFavourites")}</Link>
            <Link href="/profile">{t("profile")}</Link>
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
