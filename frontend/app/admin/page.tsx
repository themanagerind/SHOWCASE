"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api } from "@/lib/api";
import { type AdminRow, dt, useAdminGate } from "@/lib/admin";

const STATUSES = ["", "TRIAL", "ACTIVE", "GRACE", "EXPIRED", "CANCELLED"];

export default function AdminRetailers() {
  const ok = useAdminGate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [data, setData] = useState<{ total: number; items: AdminRow[] } | null>(null);

  useEffect(() => {
    if (!ok) return;
    const id = setTimeout(() => {
      const qs = new URLSearchParams({ limit: "100" });
      if (q.trim()) qs.set("q", q.trim());
      if (status === "NONE") qs.set("no_plan", "true");
      else if (status) qs.set("status", status);
      api<{ total: number; items: AdminRow[] }>(`/admin/retailers?${qs}`).then(setData);
    }, 250);
    return () => clearTimeout(id);
  }, [ok, q, status]);

  if (!ok) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Retailers {data && <span className="muted">({data.total})</span>}</h1>
      <div className="row">
        <input type="text" placeholder="Search shop, phone, city" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ flex: "0 0 140px" }}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
          <option value="NONE">No plan</option>
        </select>
      </div>
      {data?.items.map((r) => (
        <Link key={r.id} href={`/admin/retailers/${r.id}`} className="card prow plink">
          <div className="info">
            <div className="pname">{r.shop_name}</div>
            <div className="muted">{r.phone} · <span className="cap">{r.city}</span> · /{r.slug}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div><span className="plan-pill">{r.plan_code ?? "—"}</span></div>
            <div className={`status-pill ${r.status === "EXPIRED" || !r.status ? "bad" : ""}`}>{r.status ?? "NO PLAN"}</div>
            <div className="note">{r.status === "GRACE" ? `grace → ${dt(r.grace_ends_at)}` : dt(r.current_period_end)}</div>
          </div>
        </Link>
      ))}
    </main>
  );
}
