"use client";

import { useEffect, useState } from "react";
import AdminNav from "@/components/AdminNav";
import { api } from "@/lib/api";
import { adminError, useAdminGate } from "@/lib/admin";

type Settings = {
  trial: { enabled: boolean; duration_value: number; duration_unit: "days" | "months"; plan_code: string };
  grace_days_default: { days: number };
  gst: { rate_bps: number; inclusive: boolean };
};

export default function AdminSettings() {
  const ok = useAdminGate();
  const [s, setS] = useState<Settings | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (ok) api<Settings>("/admin/settings").then(setS); }, [ok]);

  async function save(key: keyof Settings) {
    try {
      await api(`/admin/settings/${key}`, { method: "PUT", body: JSON.stringify(s![key]) });
      setMsg({ ok: true, text: `${key} saved` });
    } catch (e) { setMsg({ ok: false, text: adminError(e) }); }
  }

  if (!ok || !s) return <main><div className="card">Loading…</div></main>;
  return (
    <main className="stack wide">
      <AdminNav />
      <h1>Settings</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}
      <div className="card stack">
        <h2>Free trial (new shops)</h2>
        <label className="check"><input type="checkbox" checked={s.trial.enabled} onChange={(e) => setS({ ...s, trial: { ...s.trial, enabled: e.target.checked } })} /> Enabled</label>
        <div className="row">
          <label className="mini">Duration<input type="text" inputMode="numeric" value={s.trial.duration_value}
            onChange={(e) => setS({ ...s, trial: { ...s.trial, duration_value: Number(e.target.value) || 0 } })} /></label>
          <label className="mini">Unit<select value={s.trial.duration_unit} onChange={(e) => setS({ ...s, trial: { ...s.trial, duration_unit: e.target.value as "days" | "months" } })}>
            <option>days</option><option>months</option></select></label>
          <label className="mini">Plan<select value={s.trial.plan_code} onChange={(e) => setS({ ...s, trial: { ...s.trial, plan_code: e.target.value } })}>
            <option>BASIC</option><option>PRO</option><option>PREMIUM</option></select></label>
        </div>
        <button className="btn" onClick={() => save("trial")}>Save trial</button>
      </div>
      <div className="card stack">
        <h2>Default grace period</h2>
        <label className="mini">Days<input type="text" inputMode="numeric" value={s.grace_days_default.days}
          onChange={(e) => setS({ ...s, grace_days_default: { days: Number(e.target.value) || 0 } })} /></label>
        <button className="btn" onClick={() => save("grace_days_default")}>Save grace</button>
      </div>
      <div className="card stack">
        <h2>GST</h2>
        <div className="row">
          <label className="mini">Rate %<input type="text" inputMode="decimal" value={s.gst.rate_bps / 100}
            onChange={(e) => setS({ ...s, gst: { ...s.gst, rate_bps: Math.round(Number(e.target.value) * 100) || 0 } })} /></label>
          <label className="check" style={{ alignSelf: "end" }}><input type="checkbox" checked={s.gst.inclusive}
            onChange={(e) => setS({ ...s, gst: { ...s.gst, inclusive: e.target.checked } })} /> Prices include GST</label>
        </div>
        <button className="btn" onClick={() => save("gst")}>Save GST</button>
      </div>
    </main>
  );
}
