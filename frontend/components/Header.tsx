"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, isLoggedIn } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { type Lang, LANGS } from "@/lib/messages";

export default function Header() {
  const { lang, setLang, t } = useI18n();
  const [loggedIn, setLoggedIn] = useState(false);
  const pathname = usePathname();
  // Re-check on every navigation: login happens via client-side routing.
  const [isRetailer, setIsRetailer] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    const yes = isLoggedIn();
    setLoggedIn(yes);
    if (yes) api<{ roles: string[] }>("/auth/me").then((me) => { setIsRetailer(me.roles.includes("retailer")); setIsAdmin(me.roles.includes("admin")); }).catch(() => {});
    else { setIsRetailer(false); setIsAdmin(false); }
  }, [pathname]);

  return (
    <header className="header">
      <Link href="/" className="brand">{t("appName")}</Link>
      <nav>
        <Link href="/discover">{t("navDiscover")}</Link>
        {loggedIn ? (
          <>
            {isAdmin && <Link href="/admin">Admin</Link>}
            {isRetailer && <Link href="/retailer">{t("r_myShop")}</Link>}
            <Link href="/bookings">{t("b_nav")}</Link>
            <Link href="/wallet">{t("w_nav")}</Link>
            <Link href="/favourites">{t("navFavourites")}</Link>
            <Link href="/profile">{t("profile")}</Link>
          </>
        ) : (
          <Link href="/login">{t("login")}</Link>
        )}
        <select className="lang-select" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label="Language">
          {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
      </nav>
    </header>
  );
}
