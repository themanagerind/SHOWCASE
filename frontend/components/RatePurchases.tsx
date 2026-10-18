"use client";

import { useEffect, useState } from "react";
import Stars from "@/components/Stars";
import { api } from "@/lib/api";
import { bookingErrorKey, fill } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/retailer";

type Item = { source_type: string; source_id: string; shop_name: string; label: string; purchased_at: string; rating: number | null; comment: string | null };

/** Customer: rate purchases of the last 30 days (SPEC 4.7); a given rating can be changed in that time. */
export default function RatePurchases({ refreshKey = 0 }: { refreshKey?: number }) {
  const { t, lang } = useI18n();
  const [items, setItems] = useState<Item[]>([]);
  const [draft, setDraft] = useState<Record<string, { rating: number; comment: string }>>({});
  const [msg, setMsg] = useState<{ id: string; ok: boolean; text: string } | null>(null);

  useEffect(() => { api<Item[]>("/reviews/me/rateable").then(setItems).catch(() => {}); }, [refreshKey]);
  if (items.length === 0) return null;

  async function send(i: Item) {
    const d = draft[i.source_id] ?? { rating: i.rating ?? 0, comment: i.comment ?? "" };
    if (!d.rating) return;
    try {
      await api("/reviews", { method: "POST", body: JSON.stringify({ source_type: i.source_type, source_id: i.source_id, rating: d.rating, comment: d.comment || null }) });
      setItems(items.map((x) => (x.source_id === i.source_id ? { ...x, rating: d.rating, comment: d.comment } : x)));
      setDraft((p) => { const n = { ...p }; delete n[i.source_id]; return n; });
      setMsg({ id: i.source_id, ok: true, text: t("rv_thanks") });
    } catch (e) {
      setMsg({ id: i.source_id, ok: false, text: t(bookingErrorKey(e)) });
    }
  }

  return (
    <>
      <h2>{t("rv_title")}</h2>
      {items.map((i) => {
        const d = draft[i.source_id];
        const editing = !!d || i.rating === null;
        const cur = d ?? { rating: i.rating ?? 0, comment: i.comment ?? "" };
        const until = new Date(new Date(i.purchased_at).getTime() + 30 * 86400e3).toISOString();
        return (
          <div className="card stack" key={i.source_id}>
            <div>
              <div className="pname">{i.shop_name}</div>
              <div className="note">{i.label} · {fmtDate(i.purchased_at, lang)}</div>
            </div>
            {editing ? (
              <>
                <Stars value={cur.rating} size={32} onChange={(v) => setDraft({ ...draft, [i.source_id]: { ...cur, rating: v } })} />
                <textarea rows={2} maxLength={1000} placeholder={t("rv_commentPh")} value={cur.comment}
                  onChange={(e) => setDraft({ ...draft, [i.source_id]: { ...cur, comment: e.target.value } })} />
                <button className="btn" disabled={!cur.rating} onClick={() => send(i)}>{i.rating ? t("rv_update") : t("rv_submit")}</button>
              </>
            ) : (
              <>
                <Stars value={i.rating!} />
                {i.comment && <div>{i.comment}</div>}
                <div className="note">{fill(t("rv_editUntil"), { date: fmtDate(until, lang) })}</div>
                <button className="btn secondary small" onClick={() => setDraft({ ...draft, [i.source_id]: { rating: i.rating!, comment: i.comment ?? "" } })}>{t("r_edit")}</button>
              </>
            )}
            {msg?.id === i.source_id && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}
          </div>
        );
      })}
    </>
  );
}
