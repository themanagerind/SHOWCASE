"use client";

import { useCallback, useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import Stars from "@/components/Stars";
import { api } from "@/lib/api";
import { adminError, dt, useAdminGate } from "@/lib/admin";

type F = { id: string; rating: number; comment: string | null; author: string; created_at: string; flag_reason: string | null; shop_name: string };

/** Admin: reviews flagged by retailers — hide (removed from page and average) or keep (SPEC 4.7). */
export default function AdminReviews() {
  const ok = useAdminGate();
  const [items, setItems] = useState<F[] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = useCallback(() => api<F[]>("/admin/reviews/flagged").then(setItems), []);
  useEffect(() => { if (ok) load(); }, [ok, load]);

  async function resolve(f: F, action: "HIDE" | "KEEP") {
    try {
      await api(`/admin/reviews/${f.id}/resolve`, { method: "POST", body: JSON.stringify({ action }) });
      setMsg({ ok: true, text: action === "HIDE" ? "Review hidden" : "Review kept" });
    } catch (e) { setMsg({ ok: false, text: adminError(e) }); }
    await load();
  }

  if (!ok || !items) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Flagged reviews ({items.length})</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}
      {items.length === 0 && <div className="card muted">Nothing to check.</div>}
      {items.map((f) => (
        <div className="card stack" key={f.id}>
          <div className="prow"><div className="info"><b>{f.shop_name}</b><div className="note">{f.author} · {dt(f.created_at)}</div></div><Stars value={f.rating} size={16} /></div>
          {f.comment && <div>“{f.comment}”</div>}
          <div className="banner warn">Retailer&apos;s reason: {f.flag_reason}</div>
          <div className="row">
            <button className="btn" onClick={() => confirm("Hide this review? It leaves the shop page and the average.") && resolve(f, "HIDE")}>Hide</button>
            <button className="btn secondary" onClick={() => resolve(f, "KEEP")}>Keep</button>
          </div>
        </div>
      ))}
    </main>
  );
}
