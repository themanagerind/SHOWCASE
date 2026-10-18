"use client";

import { useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api } from "@/lib/api";
import { type Audit, dt, useAdminGate } from "@/lib/admin";

export default function AdminAudit() {
  const ok = useAdminGate();
  const [rows, setRows] = useState<Audit[] | null>(null);
  useEffect(() => { if (ok) api<Audit[]>("/admin/audit?limit=200").then(setRows); }, [ok]);
  if (!ok || !rows) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Audit log</h1>
      <div className="note">Every admin change is recorded here and can never be edited or deleted.</div>
      <div className="card">
        {rows.length === 0 && <div className="muted">No changes yet</div>}
        {rows.map((a) => (
          <div key={a.id} className="audit">
            <b>{a.action}</b> · {dt(a.created_at)} · {a.admin_phone}
            <pre>{JSON.stringify({ old: a.old_value, new: a.new_value })}</pre>
          </div>
        ))}
      </div>
    </main>
  );
}
