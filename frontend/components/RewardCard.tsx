"use client";

import { useEffect, useState } from "react";
import { api, rupees } from "@/lib/api";
import { bookingErrorKey, fill } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";
import { intlLocale } from "@/lib/messages";
import { fmtDate } from "@/lib/retailer";

type Offer = { id: string; name: string; starts_at: string; ends_at: string; threshold_paise: number; percent_bp: number; status: string };
type Payout = { offer_name: string | null; payout_paise: number; paid_on: string; balance_at_end_paise: number };
type Mine = { offer: Offer | null; joined: boolean; collected_paise: number; payouts: Payout[] };

/** Retailer dashboard: the running/upcoming reward offer (SPEC 4.5) with progress, join/leave and past payouts. */
export default function RewardCard() {
  const { t, lang } = useI18n();
  const [m, setM] = useState<Mine | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Mine>("/retailers/me/reward-offer").then(setM).catch(() => {}); }, []);

  async function toggle(action: "join" | "leave") {
    if (action === "leave" && !confirm(t("rw_confirmLeave"))) return;
    setErr(null);
    try { setM(await api<Mine>(`/retailers/me/reward-offers/${m!.offer!.id}/${action}`, { method: "POST" })); }
    catch (e) { setErr(t(bookingErrorKey(e))); }
  }

  if (!m || (!m.offer && m.payouts.length === 0)) return null;
  const o = m.offer;
  const pctDone = o ? Math.min(100, Math.floor((m.collected_paise * 100) / o.threshold_paise)) : 0;
  return (
    <div className="card stack reward">
      <h2>🎁 {t("rw_title")}</h2>
      {o && (
        <>
          <div className="pname">{o.name}</div>
          <div>{fill(t("rw_text"), { threshold: rupees(o.threshold_paise), percent: o.percent_bp / 100,
            start: fmtDate(o.starts_at, lang), end: fmtDate(o.ends_at, lang) })}</div>
          {m.joined ? (
            <>
              <div className="note">{t("rw_progress")}: <b>{rupees(m.collected_paise)}</b> / {rupees(o.threshold_paise)}</div>
              <div className="bar"><span style={{ width: `${pctDone}%` }} /></div>
              {pctDone >= 100 && <div className="banner ok">{t("rw_reached")}</div>}
              <div className="note">{t("rw_resetNote")}</div>
              <button className="btn secondary" onClick={() => toggle("leave")}>{t("rw_leave")}</button>
            </>
          ) : (
            <button className="btn" onClick={() => toggle("join")}>{t("rw_join")}</button>
          )}
          {err && <div className="banner warn">{err}</div>}
        </>
      )}
      {m.payouts.length > 0 && (
        <>
          <div className="muted">{t("rw_payouts")}</div>
          {m.payouts.map((p, i) => (
            <div className="note" key={i}>
              {p.offer_name}: {fill(t("rw_paidText"), { amount: rupees(p.payout_paise), date: new Date(`${p.paid_on}T00:00:00+05:30`).toLocaleDateString(intlLocale(lang), { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" }) })}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
