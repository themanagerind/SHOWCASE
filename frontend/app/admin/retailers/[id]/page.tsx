"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api, rupees } from "@/lib/api";
import { adminError, dt, type RetailerDetail, useAdminGate } from "@/lib/admin";
import { toPaise } from "@/lib/retailer";

const PLANS = ["BASIC", "PRO", "PREMIUM"];
const CYCLES = ["MONTHLY", "YEARLY"];

export default function AdminRetailer() {
  const ok = useAdminGate();
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<RetailerDetail | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pay, setPay] = useState({ plan_code: "BASIC", billing_cycle: "MONTHLY", reference: "", amount: "" });
  const [graceDays, setGraceDays] = useState("7");
  const [ov, setOv] = useState({ amount: "", reason: "" });
  const [offer, setOffer] = useState({ offer_type: "PERCENT", value: "", plan_code: "", billing_cycle: "", from: "", until: "", reason: "" });
  const [planNow, setPlanNow] = useState("PRO");

  const load = useCallback(() => api<RetailerDetail>(`/admin/retailers/${id}`).then(setD), [id]);
  useEffect(() => { if (ok) load(); }, [ok, load]);

  async function act(label: string, fn: () => Promise<unknown>) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: `${label}: done` });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: `${label}: ${adminError(e)}` });
    }
  }

  if (!ok || !d) return <main><div className="card">Loading…</div></main>;
  const s = d.subscription;
  const post = (path: string, body: unknown, method = "POST") =>
    api(`/admin/retailers/${id}${path}`, { method, body: JSON.stringify(body) });

  return (
    <main className="stack wide">
      <AdminNav />
      <div className="card stack">
        <h1>{d.retailer.shop_name}</h1>
        <div className="muted">{d.retailer.phone} · <span className="cap">{d.retailer.city}</span> · <a href={`/${d.retailer.slug}`}>/{d.retailer.slug}</a></div>
        <div>
          <span className="plan-pill">{s.plan_code ?? "—"}</span>
          <span className={`status-pill ${s.status === "EXPIRED" || !s.status ? "bad" : ""}`}>{s.status ?? "NO PLAN"}</span>
          {s.billing_cycle && <span className="muted"> · {s.billing_cycle}</span>}
        </div>
        <table className="kv">
          <tbody>
            <tr><td>Trial ends</td><td>{dt(s.trial_ends_at)}</td></tr>
            <tr><td>Current period ends</td><td>{dt(s.current_period_end)}</td></tr>
            <tr><td>Grace ends</td><td>{dt(s.grace_ends_at)} ({d.grace_days} days)</td></tr>
            <tr><td>Next paid period</td><td>{s.next_period ? `${s.next_period.plan_code} ${dt(s.next_period.period_start)} → ${dt(s.next_period.period_end)}` : "—"}</td></tr>
            <tr><td>Price override</td><td>{d.price_override_paise != null ? `${rupees(d.price_override_paise)} — ${d.price_override_reason}` : "—"}</td></tr>
          </tbody>
        </table>
      </div>

      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      <div className="card stack">
        <h2>Record payment (UPI / cash)</h2>
        <div className="row">
          <select value={pay.plan_code} onChange={(e) => setPay({ ...pay, plan_code: e.target.value })}>{PLANS.map((p) => <option key={p}>{p}</option>)}</select>
          <select value={pay.billing_cycle} onChange={(e) => setPay({ ...pay, billing_cycle: e.target.value })}>{CYCLES.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        <div className="row">
          <input type="text" placeholder="UTR / receipt no." value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} />
          <input type="text" inputMode="decimal" placeholder="Amount ₹ (blank = plan price)" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} />
        </div>
        <button className="btn" disabled={pay.reference.trim().length < 2} onClick={() => act("Payment", () => post("/payments", {
          plan_code: pay.plan_code, billing_cycle: pay.billing_cycle, reference: pay.reference.trim(),
          amount_paise: pay.amount.trim() ? toPaise(pay.amount) : null,
        }))}>Mark paid</button>
        <div className="note">If the retailer is in a trial or a paid period, the new period starts when the current one ends.</div>
      </div>

      <div className="card stack">
        <h2>Extend grace period</h2>
        <div className="row">
          <input type="text" inputMode="numeric" value={graceDays} onChange={(e) => setGraceDays(e.target.value)} />
          <button className="btn" onClick={() => act("Grace", () => post("/grace", { extra_days: Number(graceDays) }))}>+ days</button>
        </div>
      </div>

      <div className="card stack">
        <h2>Change plan now <span className="note">(SUPER_ADMIN)</span></h2>
        <div className="row">
          <select value={planNow} onChange={(e) => setPlanNow(e.target.value)}>{PLANS.map((p) => <option key={p}>{p}</option>)}</select>
          <button className="btn" onClick={() => confirm(`Change plan to ${planNow} immediately?`) && act("Plan", () => post("/plan", { plan_code: planNow }))}>Change now</button>
        </div>
      </div>

      <div className="card stack">
        <h2>Price override <span className="note">(SUPER_ADMIN)</span></h2>
        <div className="row">
          <input type="text" inputMode="decimal" placeholder="₹ (blank = remove)" value={ov.amount} onChange={(e) => setOv({ ...ov, amount: e.target.value })} />
          <input type="text" placeholder="Reason" value={ov.reason} onChange={(e) => setOv({ ...ov, reason: e.target.value })} />
        </div>
        <button className="btn secondary" disabled={ov.reason.trim().length < 3} onClick={() => act("Override", () => post("/price-override", {
          amount_paise: ov.amount.trim() ? toPaise(ov.amount) : null, reason: ov.reason.trim(),
        }, "PUT"))}>Save override</button>
      </div>

      <div className="card stack">
        <h2>Offers <span className="note">(SUPER_ADMIN)</span></h2>
        {d.offers.map((o) => (
          <div key={o.id} className={`prow ${o.revoked_at ? "muted-row" : ""}`}>
            <div className="info">
              <b>{o.offer_type === "PERCENT" ? `${o.value}% off` : o.offer_type === "FIXED_DISCOUNT" ? `${rupees(o.value)} off` : `Price ${rupees(o.value)}`}</b>
              {" "}· {o.plan_code ?? "any plan"} · {o.billing_cycle ?? "any cycle"}
              <div className="note">{dt(o.valid_from)} → {dt(o.valid_until)} · {o.reason}{o.revoked_at && " · REVOKED"}</div>
            </div>
            {!o.revoked_at && <button className="small-btn danger" onClick={() => act("Revoke", () => api(`/admin/retailers/${id}/offers/${o.id}`, { method: "DELETE" }))}>Revoke</button>}
          </div>
        ))}
        <div className="row">
          <select value={offer.offer_type} onChange={(e) => setOffer({ ...offer, offer_type: e.target.value })}>
            <option value="PERCENT">% off</option><option value="FIXED_DISCOUNT">₹ off</option><option value="CUSTOM_PRICE">Custom price ₹</option>
          </select>
          <input type="text" inputMode="decimal" placeholder={offer.offer_type === "PERCENT" ? "Percent" : "₹"} value={offer.value} onChange={(e) => setOffer({ ...offer, value: e.target.value })} />
        </div>
        <div className="row">
          <select value={offer.plan_code} onChange={(e) => setOffer({ ...offer, plan_code: e.target.value })}><option value="">Any plan</option>{PLANS.map((p) => <option key={p}>{p}</option>)}</select>
          <select value={offer.billing_cycle} onChange={(e) => setOffer({ ...offer, billing_cycle: e.target.value })}><option value="">Any cycle</option>{CYCLES.map((c) => <option key={c}>{c}</option>)}</select>
        </div>
        <div className="row">
          <label className="mini">From<input type="date" value={offer.from} onChange={(e) => setOffer({ ...offer, from: e.target.value })} /></label>
          <label className="mini">Until<input type="date" value={offer.until} onChange={(e) => setOffer({ ...offer, until: e.target.value })} /></label>
        </div>
        <input type="text" placeholder="Reason" value={offer.reason} onChange={(e) => setOffer({ ...offer, reason: e.target.value })} />
        <button className="btn secondary" disabled={!offer.value || !offer.from || !offer.until || offer.reason.trim().length < 3}
          onClick={() => act("Offer", () => post("/offers", {
            offer_type: offer.offer_type,
            value: offer.offer_type === "PERCENT" ? Number(offer.value) : toPaise(offer.value),
            plan_code: offer.plan_code || null, billing_cycle: offer.billing_cycle || null,
            // dates are IST calendar days
            valid_from: `${offer.from}T00:00:00+05:30`, valid_until: `${offer.until}T23:59:59+05:30`, reason: offer.reason.trim(),
          }))}>Create offer</button>
      </div>

      <div className="card stack">
        <h2>Payments</h2>
        {s.payments.length === 0 && <div className="muted">None yet</div>}
        {s.payments.map((p) => (
          <div key={p.id} className="prow">
            <div className="info">{p.plan_code} · {p.billing_cycle} · {p.gateway}{p.reference && ` (${p.reference})`}
              <div className="note">{dt(p.period_start)} → {dt(p.period_end)}</div></div>
            <b>{rupees(p.amount_paise)}</b>
          </div>
        ))}
      </div>

      <div className="card stack">
        <h2>Audit log</h2>
        {d.audit.map((a) => (
          <div key={a.id} className="audit">
            <b>{a.action}</b> · {dt(a.created_at)} · {a.admin_phone}
            <pre>{JSON.stringify({ old: a.old_value, new: a.new_value })}</pre>
          </div>
        ))}
      </div>
    </main>
  );
}
