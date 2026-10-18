"use client";

import Link from "next/link";
import RetailerNav from "@/components/RetailerNav";
import { useI18n } from "@/lib/i18n";

/** Shown instead of Products / Share & QR / Customers while the shop has no live plan (SPEC 5). */
export default function PlanLocked() {
  const { t } = useI18n();
  return (
    <main className="stack">
      <RetailerNav />
      <div className="card stack">
        <h2>🔒 {t("r_lockedTitle")}</h2>
        <div>{t("r_lockedExpired")}</div>
        <Link className="btn" href="/retailer/plan">{t("p_renew")}</Link>
        <Link className="btn secondary" href="/retailer/bookings">{t("rb_title")}</Link>
      </div>
    </main>
  );
}
