"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, isLoggedIn, rupees } from "@/lib/api";
import { type Booking, bookingErrorKey, type DiscountRequest, fill, timeLeft } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { fmtDate } from "@/lib/retailer";

function BookingsInner() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const isNew = useSearchParams().get("new") === "1";
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [requests, setRequests] = useState<DiscountRequest[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [b, r] = await Promise.all([api<Booking[]>("/bookings/me"), api<DiscountRequest[]>("/shop-discounts/me")]);
    setBookings(b);
    setRequests(r);
  }, []);

  useEffect(() => {
    if (!isLoggedIn()) { router.replace("/login?next=/bookings"); return; }
    if (isNew) { setMsg({ ok: true, text: t("b_reservedOk") }); router.replace("/bookings"); } // show once, not on reload
    load();
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    const poll = setInterval(load, 60_000); // discount requests arrive while the customer is at the counter
    return () => { clearInterval(tick); clearInterval(poll); };
  }, [router, load]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(id: string, path: string, okText: string) {
    setBusy(id);
    setMsg(null);
    try {
      await api(path, { method: "POST" });
      setMsg({ ok: true, text: okText });
    } catch (e) {
      setMsg({ ok: false, text: t(bookingErrorKey(e)) });
    } finally {
      setBusy(null);
      await load();
    }
  }

  if (!bookings) return <main><div className="card">{t("loading")}</div></main>;
  const open = bookings.filter((b) => b.status === "RESERVED" && new Date(b.expires_at).getTime() > now);
  const past = bookings.filter((b) => !open.includes(b));

  return (
    <main className="stack">
      <h1>{t("b_title")}</h1>
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      {requests.length > 0 && (
        <>
          <h2>{t("d_requests")}</h2>
          {requests.map((r) => (
            <div className="card stack" key={r.id}>
              <div>{fill(t("d_requestText"), { shop: r.shop_name ?? "", amount: rupees(r.amount_paise), note: r.note })}</div>
              <div className="note">{t("b_timeLeft")}: <span className="countdown">{timeLeft(r.expires_at, now)}</span></div>
              <div className="row">
                <button className="btn" disabled={busy === r.id}
                  onClick={() => confirm(fill(t("d_confirmAccept"), { amount: rupees(r.amount_paise), shop: r.shop_name ?? "" }))
                    && act(r.id, `/shop-discounts/${r.id}/accept`, t("d_done"))}>{t("d_accept")}</button>
                <button className="btn secondary" disabled={busy === r.id}
                  onClick={() => act(r.id, `/shop-discounts/${r.id}/decline`, t("d_declined"))}>{t("d_decline")}</button>
              </div>
            </div>
          ))}
        </>
      )}

      {open.length === 0 && past.length === 0 && <div className="card muted">{t("b_empty")}</div>}
      {open.map((b) => (
        <div className="card stack" key={b.id}>
          <div className="prow">
            <div className="info">
              <div className="pname">{b.product_name}</div>
              <div className="note">
                {b.shop_slug ? <Link href={`/${b.shop_slug}`}>{b.shop_name}</Link> : b.shop_name} · {rupees(b.price_paise)}
              </div>
            </div>
            <span className="status RESERVED">{t("b_s_RESERVED")}</span>
          </div>
          <div>
            <div className="note">{t("b_showAtCounter")}</div>
            <div className="booking-no">{b.booking_no}</div>
          </div>
          <div className="note">
            {t("b_points")}: <b>{rupees(b.discount_paise)}</b> · {t("b_timeLeft")}: <span className="countdown">{timeLeft(b.expires_at, now)}</span>
          </div>
          <button className="btn" disabled={busy === b.id}
            onClick={() => confirm(fill(t("b_confirmBought"), { points: rupees(b.discount_paise) }))
              && act(b.id, `/bookings/${b.id}/purchased`, t("b_boughtOk"))}>{t("b_bought")}</button>
          <div className="note">{t("b_forfeitNote")}</div>
        </div>
      ))}

      {past.length > 0 && <h2>{t("b_history")}</h2>}
      {past.map((b) => {
        // A RESERVED booking past its time is forfeited by the 5-minute job; show it as such already.
        const status = b.status === "RESERVED" ? "FORFEITED" : b.status;
        return (
          <div className="card prow" key={b.id}>
            <div className="info">
              <div className="pname">{b.product_name}</div>
              <div className="note">{b.shop_name} · {b.booking_no} · {fmtDate(b.created_at, lang)}</div>
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

export default function BookingsPage() {
  return <Suspense><BookingsInner /></Suspense>;
}
