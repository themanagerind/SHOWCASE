"use client";

import { useCallback, useEffect, useState } from "react";
import RetailerNav from "@/components/RetailerNav";
import { api, rupees } from "@/lib/api";
import { type Booking, bookingErrorKey, type DiscountRequest, timeLeft } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { fmtDate, toPaise, useMyShop } from "@/lib/retailer";

export default function RetailerBookingsPage() {
  const { t, lang } = useI18n();
  const { shop } = useMyShop();
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [requests, setRequests] = useState<DiscountRequest[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ phone: "", amount: "", note: "" });

  const load = useCallback(async () => {
    const [b, r] = await Promise.all([api<Booking[]>("/retailers/me/bookings"), api<DiscountRequest[]>("/retailers/me/shop-discounts")]);
    setBookings(b);
    setRequests(r);
  }, []);

  useEffect(() => {
    if (!shop) return;
    load();
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    const poll = setInterval(load, 30_000); // see the customer's confirmation without reloading
    return () => { clearInterval(tick); clearInterval(poll); };
  }, [shop, load]);

  async function cancel(b: Booking) {
    const reason = prompt(t("rb_reasonPrompt"));
    if (!reason || reason.trim().length < 2) return;
    setMsg(null);
    try {
      await api(`/retailers/me/bookings/${b.id}/cancel`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) });
      setMsg({ ok: true, text: t("rb_cancelled") });
    } catch (e) {
      setMsg({ ok: false, text: t(bookingErrorKey(e)) });
    }
    await load();
  }

  async function sendDiscount(e: React.FormEvent) {
    e.preventDefault();
    const amount = toPaise(form.amount);
    if (!(amount > 0)) { setMsg({ ok: false, text: t("rd_errAmount") }); return; }
    setBusy(true);
    setMsg(null);
    try {
      await api("/retailers/me/shop-discounts", { method: "POST",
        body: JSON.stringify({ phone: form.phone, amount_paise: amount, note: form.note.trim() }) });
      setMsg({ ok: true, text: t("rd_sent") });
      setForm({ phone: "", amount: "", note: "" });
    } catch (err) {
      setMsg({ ok: false, text: t(bookingErrorKey(err)) });
    } finally {
      setBusy(false);
      await load();
    }
  }

  if (!shop || !bookings) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;
  const open = bookings.filter((b) => b.status === "RESERVED" && new Date(b.expires_at).getTime() > now);
  const past = bookings.filter((b) => !open.includes(b));
  const who = (x: { customer_name: string | null; customer_phone: string | null }) =>
    [x.customer_name, x.customer_phone].filter(Boolean).join(" · ");

  return (
    <main className="stack">
      <RetailerNav />
      <h1>{t("rb_title")}</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      <h2>{t("rb_open")} ({open.length})</h2>
      <div className="banner info">{t("rb_help")}</div>
      {open.length === 0 && <div className="card muted">{t("rb_none")}</div>}
      {open.map((b) => (
        <div className="card stack" key={b.id}>
          <div className="prow">
            <div className="info">
              <div className="booking-no">{b.booking_no}</div>
              <div className="pname">{b.product_name}</div>
              <div className="note">{who(b)}</div>
            </div>
          </div>
          <div className="note">
            {t("b_points")}: <b>{rupees(b.discount_paise)}</b> · {t("b_timeLeft")}: <span className="countdown">{timeLeft(b.expires_at, now)}</span>
          </div>
          <button className="btn secondary" onClick={() => cancel(b)}>{t("rb_cancel")}</button>
        </div>
      ))}

      <form className="card stack" onSubmit={sendDiscount}>
        <h2>{t("rd_title")}</h2>
        <div className="note">{t("rd_help")}</div>
        <label>{t("rd_phone")}
          <input type="tel" inputMode="numeric" value={form.phone} maxLength={13} required
            onChange={(e) => setForm({ ...form, phone: e.target.value.replace(/[^\d+]/g, "") })} />
        </label>
        <label>{t("rd_amount")}
          <input type="text" inputMode="decimal" value={form.amount} required
            onChange={(e) => setForm({ ...form, amount: e.target.value })} />
        </label>
        <label>{t("rd_note")}
          <input type="text" value={form.note} minLength={2} maxLength={120} required
            onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </label>
        <button className="btn" disabled={busy}>{t("rd_send")}</button>
      </form>

      {requests.length > 0 && (
        <>
          <h2>{t("rd_recent")}</h2>
          {requests.map((r) => {
            const status = r.status === "PENDING" && new Date(r.expires_at).getTime() <= now ? "EXPIRED" : r.status;
            return (
              <div className="card prow" key={r.id}>
                <div className="info">
                  <div className="pname">{r.note}</div>
                  <div className="note">{who(r)} · {fmtDate(r.created_at, lang)}</div>
                </div>
                <div className="side">
                  <div className="amount">{rupees(r.amount_paise)}</div>
                  <span className={`status ${status}`}>{t(`rd_s_${status}` as MessageKey)}</span>
                </div>
              </div>
            );
          })}
        </>
      )}

      {past.length > 0 && <h2>{t("rb_history")}</h2>}
      {past.map((b) => {
        const status = b.status === "RESERVED" ? "FORFEITED" : b.status;
        return (
          <div className="card prow" key={b.id}>
            <div className="info">
              <div className="pname">{b.product_name}</div>
              <div className="note">{b.booking_no} · {who(b)} · {fmtDate(b.created_at, lang)}</div>
              {b.cancel_reason && <div className="note">{t("b_reason")}: {b.cancel_reason}</div>}
            </div>
            <div className="side">
              <span className={`status ${status}`}>{t(`b_s_${status}` as MessageKey)}</span>
              <div className="note">{rupees(b.discount_paise)}</div>
            </div>
          </div>
        );
      })}
    </main>
  );
}
