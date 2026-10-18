"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, rupees } from "@/lib/api";
import RetailerNav from "@/components/RetailerNav";
import { useI18n } from "@/lib/i18n";
import { fmtDate, useMyShop } from "@/lib/retailer";

export default function RetailerDashboard() {
  const { t, lang } = useI18n();
  const { shop } = useMyShop();
  const [walletPaise, setWalletPaise] = useState<number | null>(null);
  useEffect(() => { if (shop) api<{ balance_paise: number }>("/retailers/me/wallet").then((w) => setWalletPaise(w.balance_paise)); }, [shop]);
  if (!shop) return <main><div className="card">{t("loading")}</div></main>;

  const live = !!shop.plan_code;
  return (
    <main className="stack">
      <RetailerNav />
      <div className="card stack">
        <div>
          <h1>{shop.shop_name}</h1>
          <div className="muted">{shop.category} · <span className="cap">{shop.city}</span></div>
        </div>
        <div>
          <span className="muted">{t("r_plan")}: </span>
          {live ? (
            <>
              <span className="plan-pill">{shop.plan_code}</span>
              <span className="status-pill">{shop.subscription_status}</span>
            </>
          ) : (
            <span className="plan-pill" style={{ background: "var(--danger)" }}>—</span>
          )}
        </div>
        {!live && <div className="banner warn">{t("r_noPlan")}</div>}
        {shop.subscription_status === "TRIAL" && <div className="banner ok">{t("p_TRIAL")}</div>}
        {shop.subscription_status === "GRACE" && <div className="banner warn">{t("p_GRACE")} — {t("p_renew")}</div>}
        <Link className="btn secondary" href="/retailer/plan">{t("p_seePlans")}</Link>
      </div>

      <div className="stats">
        <div className="stat">
          <div className="num">
            {shop.active_products}
            <span style={{ fontSize: 16, color: "var(--muted)" }}> / {shop.max_products ?? t("r_unlimited")}</span>
          </div>
          <div className="lbl">{t("r_activeProducts")}</div>
        </div>
        <div className="stat">
          <div className="num">{shop.customers_count}</div>
          <div className="lbl">{t("r_totalCustomers")}</div>
        </div>
        <div className="stat" style={{ gridColumn: "1 / -1" }}>
          <div className="num" style={{ color: "var(--green)" }}>{walletPaise === null ? "…" : rupees(walletPaise)}</div>
          <div className="lbl">{t("r_walletPoints")}</div>
        </div>
      </div>

      {live && (
        shop.products_locked_until ? (
          <div className="banner warn">
            🔒 {t("r_lockedUntil")} <b>{fmtDate(shop.products_locked_until, lang)}</b>
            <br />{t("r_lockedHelp")}
          </div>
        ) : !shop.swap_locks ? (
          <div className="banner ok">{t("r_noLock")}</div>
        ) : shop.first_listing_free ? (
          <div className="banner ok">{t("r_firstListing")}</div>
        ) : (
          <div className="banner info">{t("r_lockWarn")}</div>
        )
      )}

      <Link className="btn" href="/retailer/products">{t("r_products")}</Link>
      <div className="row">
        <Link className="btn secondary" href="/retailer/share">{t("r_share")}</Link>
        <Link className="btn secondary" href={`/${shop.slug}`}>{t("r_viewShop")}</Link>
      </div>
    </main>
  );
}
