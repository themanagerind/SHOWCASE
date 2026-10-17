"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n";

export default function Home() {
  const { t } = useI18n();
  return (
    <main className="stack">
      <div className="card">
        <h1>{t("appName")}</h1>
        <p className="muted">{t("tagline")}</p>
      </div>
      <Link className="btn" href="/discover">{t("discover")}</Link>
      <Link className="btn secondary" href="/favourites">{t("favourites")}</Link>
      <Link className="btn secondary" href="/retailer">🏪 {t("r_ownShopCta")}</Link>
    </main>
  );
}
