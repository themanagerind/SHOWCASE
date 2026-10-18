"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { intlLocale } from "@/lib/messages";

type DeviceSession = { id: string; device: string; started_at: string; last_active_at: string; current: boolean };

/** "Logged-in devices": log out one device, or all others (e.g. a lost phone). */
export default function DeviceSessions() {
  const { t, lang } = useI18n();
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const load = useCallback(() => api<DeviceSession[]>("/auth/sessions").then(setList).catch(() => setList([])), []);
  useEffect(() => { load(); }, [load]);
  if (!list || list.length === 0) return null;

  const when = (iso: string) => new Date(iso).toLocaleString(intlLocale(lang), {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });

  return (
    <div className="card stack" style={{ marginTop: 12 }}>
      <h2>{t("s_devices")}</h2>
      {list.map((s) => (
        <div className="prow" key={s.id}>
          <div className="info">
            <div className="pname">📱 {s.device}{s.current && <span className="status-pill">{t("s_thisDevice")}</span>}</div>
            <div className="note">{t("s_lastActive")}: {when(s.last_active_at)}</div>
          </div>
          {!s.current && (
            <button className="small-btn danger" onClick={async () => { await api(`/auth/sessions/${s.id}/logout`, { method: "POST" }); load(); }}>
              {t("s_logoutDevice")}
            </button>
          )}
        </div>
      ))}
      {list.length > 1 && (
        <button className="btn secondary" onClick={async () => {
          if (!confirm(t("s_confirmOthers"))) return;
          await api("/auth/logout-all", { method: "POST", body: JSON.stringify({ keep_current: true }) });
          load();
        }}>{t("s_logoutOthers")}</button>
      )}
    </div>
  );
}
