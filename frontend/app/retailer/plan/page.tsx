"use client";

import { useCallback, useEffect, useState } from "react";
import RetailerNav from "@/components/RetailerNav";
import { api, rupees } from "@/lib/api";
import { PageLoading } from "@/components/LoadError";
import { useI18n } from "@/lib/i18n";
import { fmtDate, useMyShop } from "@/lib/retailer";
import { type Checkout, loadRazorpay, type MySubscription, openRazorpay, type PlanOption } from "@/lib/subscription";

export default function PlanPage() {
  const { t, lang } = useI18n();
  const { shop, reload, failed: shopFailed } = useMyShop();
  const [failed, setFailed] = useState(false);
  const [sub, setSub] = useState<MySubscription | null>(null);
  const [plans, setPlans] = useState<PlanOption[] | null>(null);
  const [cycle, setCycle] = useState<"MONTHLY" | "YEARLY">("YEARLY");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [s, p] = await Promise.all([api<MySubscription>("/subscriptions/me"), api<PlanOption[]>("/subscriptions/plans")]);
    setSub(s);
    setPlans(p);
    // Paid subscribers see their own cycle; everyone else starts on yearly (the better deal).
    if (s.status === "ACTIVE" && s.billing_cycle) setCycle(s.billing_cycle);
  }, []);
  useEffect(() => { if (shop) load().catch(() => setFailed(true)); }, [shop, load]);

  async function pay(code: string) {
    setMsg(null);
    setBusy(code);
    try {
      const co = await api<Checkout>("/subscriptions/me/checkout", { method: "POST", body: JSON.stringify({ plan_code: code, billing_cycle: cycle }) });
      const R = await loadRazorpay();
      const resp = await openRazorpay(R, co, shop!.shop_name);
      await api(`/subscriptions/me/checkout/${co.payment_id}/confirm`, {
        method: "POST", body: JSON.stringify({ razorpay_payment_id: resp.razorpay_payment_id, razorpay_signature: resp.razorpay_signature }),
      });
      setMsg({ ok: true, text: t("p_paid") });
      await Promise.all([load(), reload()]);
    } catch {
      setMsg({ ok: false, text: t("p_payFailed") });
    } finally {
      setBusy(null);
    }
  }

  if (!shop || !sub || !plans) return <PageLoading failed={failed || shopFailed} nav />;

  const status = sub.status ?? "none";
  const statusKey = (["TRIAL", "ACTIVE", "GRACE", "EXPIRED"].includes(status) ? `p_${status}` : "p_none") as
    "p_TRIAL" | "p_ACTIVE" | "p_GRACE" | "p_EXPIRED" | "p_none";
  const live = ["TRIAL", "ACTIVE", "GRACE"].includes(status);
  const scopeKey = (s: unknown) => `p_scope_${String(s)}` as "p_scope_PINCODE" | "p_scope_CITY" | "p_scope_INDIA";

  return (
    <main className="stack">
      <RetailerNav />
      <div className="card stack">
        <h1>{t("p_title")}</h1>
        <div>
          {sub.plan_code && <span className="plan-pill">{sub.plan_code}</span>}
          <span className={`status-pill ${live ? "" : "bad"}`}>{t(statusKey)}</span>
          {sub.billing_cycle && status !== "TRIAL" && <span className="muted"> · {t(sub.billing_cycle === "YEARLY" ? "p_yearly" : "p_monthly")}</span>}
        </div>
        {status === "TRIAL" && sub.trial_ends_at && <div className="banner ok">{t("p_trialEnds")}: <b>{fmtDate(sub.trial_ends_at, lang)}</b></div>}
        {status === "ACTIVE" && sub.current_period_end && <div className="banner ok">{t("p_validUntil")}: <b>{fmtDate(sub.current_period_end, lang)}</b></div>}
        {status === "GRACE" && sub.grace_ends_at && <div className="banner warn">{t("p_graceEnds")}: <b>{fmtDate(sub.grace_ends_at, lang)}</b></div>}
        {status === "EXPIRED" && <div className="banner warn">{t("p_expiredHelp")}</div>}
        {status === "none" && <div className="banner info">{t("p_noneHelp")}</div>}
        {sub.next_period && (
          <div className="banner info">
            {t("p_next")} <b>{sub.next_period.plan_code}</b> · {fmtDate(sub.next_period.period_start!, lang)} → {fmtDate(sub.next_period.period_end!, lang)}
          </div>
        )}
      </div>

      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      <div className="tabs" role="tablist">
        {(["MONTHLY", "YEARLY"] as const).map((c) => (
          <button key={c} role="tab" aria-selected={cycle === c} className={cycle === c ? "on" : ""} onClick={() => setCycle(c)}>
            {t(c === "YEARLY" ? "p_yearly" : "p_monthly")}{c === "YEARLY" && <span className="save-chip">{t("p_yearlySave")}</span>}
          </button>
        ))}
      </div>

      {plans.map((p) => {
        const price = cycle === "YEARLY" ? p.yearly : p.monthly;
        const isCurrent = p.code === sub.plan_code && live;
        const max = p.features.max_products as number | null;
        return (
          <div className={`card stack plan-card ${isCurrent ? "current" : ""}`} key={p.code}>
            <div className="row" style={{ alignItems: "baseline" }}>
              <h2 style={{ margin: 0 }}>{p.name}</h2>
              {isCurrent && <span className="status-pill" style={{ textAlign: "right", flex: "none" }}>{t("p_current")}</span>}
            </div>
            <div>
              <span className="big-price">{rupees(price.amount_paise)}</span>
              <span className="muted">{t(cycle === "YEARLY" ? "p_perYear" : "p_perMonth")}</span>
              {price.amount_paise < price.base_paise && <span className="mrp">{rupees(price.base_paise)}</span>}
              <div className="note">{t("p_gstIncl")} ({rupees(price.gst_paise)})</div>
              {price.source !== "BASE" && <span className="badge">{t("p_offer")}</span>}
            </div>
            <ul className="features">
              <li>✓ {max == null ? t("p_unlimitedProducts") : t("p_products").replace("{n}", String(max))}</li>
              <li>✓ {t(scopeKey(p.features.visibility_scope))}</li>
            </ul>
            {sub.online_payment_available ? (
              <button className="btn" disabled={busy !== null} onClick={() => pay(p.code)}>
                {busy === p.code ? t("loading") : `${isCurrent ? t("p_renew") : t("p_choose")} · ${t("p_pay")} ${rupees(price.amount_paise)}`}
              </button>
            ) : null}
          </div>
        );
      })}

      {!sub.online_payment_available && <div className="banner info">{t("p_offlineHelp")}</div>}
      {live && <div className="note">{t("p_renewalNote")}</div>}

      {sub.payments.length > 0 && (
        <>
          <h2>{t("p_history")}</h2>
          {sub.payments.map((p) => (
            <div className="card prow" key={p.id}>
              <div className="info">
                <div className="pname">{p.plan_code} · {t(p.billing_cycle === "YEARLY" ? "p_yearly" : "p_monthly")}</div>
                <div className="muted">{fmtDate(p.period_start!, lang)} → {fmtDate(p.period_end!, lang)}</div>
              </div>
              <div className="price">{rupees(p.amount_paise)}</div>
            </div>
          ))}
        </>
      )}
    </main>
  );
}
