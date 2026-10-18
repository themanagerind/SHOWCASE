"use client";

import { useCallback, useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api, rupees } from "@/lib/api";
import { type AdminPlan, adminError, useAdminGate } from "@/lib/admin";
import { toPaise, toRupeesInput } from "@/lib/retailer";

function PlanEditor({ plan, onSaved }: { plan: AdminPlan; onSaved: (m: { ok: boolean; text: string }) => void }) {
  const [monthly, setMonthly] = useState(toRupeesInput(plan.monthly_paise));
  const [yearly, setYearly] = useState(toRupeesInput(plan.yearly_paise));
  const [applyTo, setApplyTo] = useState<"NEW_ONLY" | "ALL">("NEW_ONLY");
  const [maxProducts, setMaxProducts] = useState(plan.features.max_products == null ? "" : String(plan.features.max_products));
  const [scope, setScope] = useState(String(plan.features.visibility_scope));

  async function savePrices() {
    try {
      const r = await api<{ grandfathered: number }>(`/admin/plans/${plan.code}/prices`, {
        method: "PUT", body: JSON.stringify({ monthly_paise: toPaise(monthly), yearly_paise: toPaise(yearly), apply_to: applyTo }),
      });
      onSaved({ ok: true, text: `${plan.code} prices saved (${r.grandfathered} existing subscriptions kept their old price)` });
    } catch (e) { onSaved({ ok: false, text: adminError(e) }); }
  }
  async function saveFeatures() {
    try {
      await api(`/admin/plans/${plan.code}/features`, {
        method: "PATCH", body: JSON.stringify({ max_products: maxProducts.trim() ? Number(maxProducts) : null, visibility_scope: scope }),
      });
      onSaved({ ok: true, text: `${plan.code} features saved` });
    } catch (e) { onSaved({ ok: false, text: adminError(e) }); }
  }

  return (
    <div className="card stack">
      <h2>{plan.name} <span className="muted">· {plan.subscribers} live subscribers</span></h2>
      <div className="note">Now: {rupees(plan.monthly_paise)}/month · {rupees(plan.yearly_paise)}/year (GST-inclusive)</div>
      <div className="row">
        <label className="mini">Monthly ₹<input type="text" inputMode="decimal" value={monthly} onChange={(e) => setMonthly(e.target.value)} /></label>
        <label className="mini">Yearly ₹<input type="text" inputMode="decimal" value={yearly} onChange={(e) => setYearly(e.target.value)} /></label>
      </div>
      <select value={applyTo} onChange={(e) => setApplyTo(e.target.value as "NEW_ONLY" | "ALL")}>
        <option value="NEW_ONLY">Apply to NEW retailers only (existing keep their price)</option>
        <option value="ALL">Apply to ALL retailers at their next renewal</option>
      </select>
      <button className="btn" onClick={() => confirm(`Change ${plan.code} prices?`) && savePrices()}>Save prices</button>
      <div className="row">
        <label className="mini">Max products (blank = unlimited)<input type="text" inputMode="numeric" value={maxProducts} onChange={(e) => setMaxProducts(e.target.value)} /></label>
        <label className="mini">Visibility<select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option>PINCODE</option><option>CITY</option><option>INDIA</option></select></label>
      </div>
      <button className="btn secondary" onClick={saveFeatures}>Save features</button>
    </div>
  );
}

export default function AdminPlans() {
  const ok = useAdminGate();
  const [plans, setPlans] = useState<AdminPlan[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => api<AdminPlan[]>("/admin/plans").then(setPlans), []);
  useEffect(() => { if (ok) load(); }, [ok, load]);
  if (!ok || !plans) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Plans & prices</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}
      {plans.map((p) => <PlanEditor key={`${p.code}-${p.monthly_paise}-${p.yearly_paise}`} plan={p} onSaved={(m) => { setMsg(m); load(); }} />)}
    </main>
  );
}
