"use client";

import { useCallback, useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api, rupees } from "@/lib/api";
import { adminError, dt, useAdminGate } from "@/lib/admin";
import { toPaise } from "@/lib/retailer";

type RewardOffer = {
  id: string; name: string; starts_at: string; ends_at: string; threshold_paise: number; percent_bp: number;
  status: "UPCOMING" | "RUNNING" | "ENDED" | "CANCELLED"; created_at: string;
};
type Payout = { payout_paise: number; balance_at_end_paise: number; paid_on: string; reference: string };
type Standing = {
  retailer_id: string; shop_name: string; phone: string | null; joined_at: string; collected_paise: number;
  qualifies: boolean; balance_at_end_paise: number | null; payout_paise: number | null; payout: Payout | null;
};
type Detail = { offer: RewardOffer; standings: Standing[] };

/** datetime-local value (typed in IST) → ISO string with the IST offset. */
const istIso = (local: string) => `${local}:00+05:30`;
const pct = (bp: number) => `${bp / 100}%`;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export default function AdminRewards() {
  const ok = useAdminGate();
  const [offers, setOffers] = useState<RewardOffer[] | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState({ name: "", start: "", end: "", threshold: "", percent: "" });
  const [pay, setPay] = useState<Record<string, { paid_on: string; reference: string }>>({});

  const load = useCallback(() => api<RewardOffer[]>("/admin/reward-offers").then(setOffers), []);
  useEffect(() => { if (ok) load(); }, [ok, load]);

  const open = (id: string) => api<Detail>(`/admin/reward-offers/${id}`).then(setDetail);

  async function run(fn: () => Promise<unknown>, okText: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: okText }); } catch (e) { setMsg({ ok: false, text: adminError(e) }); }
    await load();
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const threshold = toPaise(form.threshold);
    const bp = Math.round(Number(form.percent) * 100);
    if (!(threshold > 0) || !(bp > 0 && bp <= 10000)) { setMsg({ ok: false, text: "Enter a valid threshold and percent (0–100)." }); return; }
    await run(() => api("/admin/reward-offers", { method: "POST", body: JSON.stringify({
      name: form.name, starts_at: istIso(form.start), ends_at: istIso(form.end), threshold_paise: threshold, percent_bp: bp,
    }) }).then(() => setForm({ name: "", start: "", end: "", threshold: "", percent: "" })), "Offer created");
  }

  async function record(s: Standing) {
    const p = pay[s.retailer_id] ?? { paid_on: today(), reference: "" };
    if (!confirm(`Record ${rupees(s.payout_paise ?? 0)} paid to ${s.shop_name}? ${rupees(s.balance_at_end_paise ?? 0)} points will be removed from their wallet.`)) return;
    await run(() => api<Detail>(`/admin/reward-offers/${detail!.offer.id}/payouts`, { method: "POST",
      body: JSON.stringify({ retailer_id: s.retailer_id, ...p }) }).then(setDetail), "Payout recorded");
  }

  if (!ok || !offers) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Retailer reward offers</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      <form className="card stack" onSubmit={create}>
        <h2>New offer</h2>
        <div className="note">Retailers who join and collect at least the threshold in the period get the percent of their wallet balance (at the end) as cash. Offers cannot overlap. Times are IST.</div>
        <label>Name<input type="text" value={form.name} minLength={3} maxLength={120} required onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Starts (IST)<input type="datetime-local" value={form.start} required onChange={(e) => setForm({ ...form, start: e.target.value })} /></label>
        <label>Ends (IST)<input type="datetime-local" value={form.end} required onChange={(e) => setForm({ ...form, end: e.target.value })} /></label>
        <div className="row">
          <label className="mini">Threshold (points, ₹)<input type="text" inputMode="decimal" value={form.threshold} required onChange={(e) => setForm({ ...form, threshold: e.target.value })} /></label>
          <label className="mini">Cash %<input type="text" inputMode="decimal" value={form.percent} required onChange={(e) => setForm({ ...form, percent: e.target.value })} /></label>
        </div>
        <button className="btn">Create offer</button>
      </form>

      <h2>Offers</h2>
      {offers.length === 0 && <div className="card muted">No offers yet.</div>}
      {offers.map((o) => (
        <div className={`card prow ${detail?.offer.id === o.id ? "selected" : ""}`} key={o.id}>
          <div className="info">
            <div className="pname">{o.name}</div>
            <div className="note">{dt(o.starts_at)} → {dt(o.ends_at)}</div>
            <div className="note">≥ {rupees(o.threshold_paise)} points → {pct(o.percent_bp)} cash</div>
          </div>
          <div className="side stack">
            <span className={`status ${o.status === "CANCELLED" ? "DECLINED" : o.status === "ENDED" ? "CONFIRMED" : "PENDING"}`}>{o.status}</span>
            <button className="btn small secondary" type="button" onClick={() => open(o.id)}>Details</button>
            {(o.status === "UPCOMING" || o.status === "RUNNING") && (
              <button className="btn small secondary" type="button"
                onClick={() => confirm(`Cancel "${o.name}"? Nobody will be paid for it.`) && run(() => api(`/admin/reward-offers/${o.id}/cancel`, { method: "POST" }), "Offer cancelled")}>Cancel</button>
            )}
          </div>
        </div>
      ))}

      {detail && (
        <div className="card stack">
          <h2>{detail.offer.name} — participants ({detail.standings.length})</h2>
          {detail.offer.status !== "ENDED" && <div className="note">Payouts can be recorded after the offer ends.</div>}
          {detail.standings.length === 0 && <div className="muted">Nobody has joined yet.</div>}
          {detail.standings.map((s) => (
            <div className="card stack" key={s.retailer_id}>
              <div className="prow">
                <div className="info">
                  <div className="pname">{s.shop_name}</div>
                  <div className="note">{s.phone} · joined {dt(s.joined_at)}</div>
                  <div className="note">Collected {rupees(s.collected_paise)} / {rupees(detail.offer.threshold_paise)}</div>
                </div>
                <div className="side">
                  <span className={`status ${s.qualifies ? "CONFIRMED" : "PENDING"}`}>{s.qualifies ? "Qualifies" : "Below target"}</span>
                  {s.payout_paise !== null && <div className="amount">{rupees(s.payout_paise)}</div>}
                </div>
              </div>
              {s.payout ? (
                <div className="success">Paid {rupees(s.payout.payout_paise)} on {s.payout.paid_on} · ref {s.payout.reference} · {rupees(s.payout.balance_at_end_paise)} points reset</div>
              ) : detail.offer.status === "ENDED" && s.qualifies && (
                <div className="row">
                  <label className="mini">Paid on<input type="date" value={pay[s.retailer_id]?.paid_on ?? today()}
                    onChange={(e) => setPay({ ...pay, [s.retailer_id]: { reference: pay[s.retailer_id]?.reference ?? "", paid_on: e.target.value } })} /></label>
                  <label className="mini">Reference (UPI / bank)<input type="text" value={pay[s.retailer_id]?.reference ?? ""} minLength={2} maxLength={120}
                    onChange={(e) => setPay({ ...pay, [s.retailer_id]: { paid_on: pay[s.retailer_id]?.paid_on ?? today(), reference: e.target.value } })} /></label>
                  <button className="btn small" type="button" disabled={(pay[s.retailer_id]?.reference ?? "").trim().length < 2}
                    onClick={() => record(s)}>Record payout</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
