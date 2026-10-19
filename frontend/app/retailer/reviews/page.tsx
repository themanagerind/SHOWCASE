"use client";

import { useCallback, useEffect, useState } from "react";
import RetailerNav from "@/components/RetailerNav";
import Stars from "@/components/Stars";
import { api } from "@/lib/api";
import { PageLoading } from "@/components/LoadError";
import { useI18n } from "@/lib/i18n";
import { fmtDate, useMyShop } from "@/lib/retailer";

type R = { id: string; rating: number; comment: string | null; author: string; created_at: string; is_flagged: boolean; flag_reason: string | null; is_hidden: boolean; resolved: boolean };

/** Retailer: all reviews of the shop; flag an abusive one for the Showcase team (SPEC 4.7). */
export default function RetailerReviews() {
  const { t, lang } = useI18n();
  const { shop, failed: shopFailed } = useMyShop();
  const [failed, setFailed] = useState(false);
  const [items, setItems] = useState<R[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => api<R[]>("/retailers/me/reviews").then(setItems, () => setFailed(true)), []);
  useEffect(() => { if (shop) load(); }, [shop, load]);

  async function flag(r: R) {
    const reason = prompt(t("rv_flagPrompt"));
    if (!reason || reason.trim().length < 3) return;
    setBusy(r.id);
    await api(`/retailers/me/reviews/${r.id}/flag`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) }).catch(() => alert(t("genericError")));
    await load();
    setBusy(null);
  }

  if (!shop || !items) return <PageLoading failed={failed || shopFailed} nav />;
  const avg = items.filter((r) => !r.is_hidden);
  return (
    <main className="stack">
      <RetailerNav />
      <h1>{t("rv_myTitle")}</h1>
      <div className="card prow">
        <div className="info"><span className="rating-big">{shop.rating_avg.toFixed(1)}</span> <Stars value={shop.rating_avg} /></div>
        <div className="note">{avg.length} {t("rv_count")}</div>
      </div>
      <div className="banner info">{t("rv_retailerHelp")}</div>
      {items.length === 0 && <div className="card muted">{t("rv_none")}</div>}
      {items.map((r) => (
        <div className={`card stack review ${r.is_hidden ? "muted-row" : ""}`} key={r.id}>
          <div className="prow"><div className="info"><b>{r.author}</b> <span className="note">· {fmtDate(r.created_at, lang)}</span></div><Stars value={r.rating} size={16} /></div>
          {r.comment && <div>{r.comment}</div>}
          {r.is_hidden ? <span className="status DECLINED">{t("rv_hidden")}</span>
            : r.resolved ? <span className="status CONFIRMED">{t("rv_kept")}</span>
            : r.is_flagged ? <span className="status PENDING">{t("rv_flagged")}</span>
            : <button className="btn secondary small" onClick={() => flag(r)} disabled={busy === r.id}>{t("rv_flag")}</button>}
        </div>
      ))}
    </main>
  );
}
