"use client";

import { useEffect, useState } from "react";
import Stars from "@/components/Stars";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/retailer";

type R = { id: string; rating: number; comment: string | null; author: string; created_at: string };
type Data = { rating_avg: number; rating_count: number; reviews: R[] };

/** Public shop page: rating summary + latest reviews (SPEC 4.7). */
export default function ShopReviews({ slug }: { slug: string }) {
  const { t, lang } = useI18n();
  const [d, setD] = useState<Data | null>(null);
  useEffect(() => { api<Data>(`/retailers/${encodeURIComponent(slug)}/reviews`).then(setD).catch(() => {}); }, [slug]);
  if (!d) return null;
  return (
    <>
      <h2>{t("rv_reviews")}</h2>
      {d.rating_count === 0 ? <div className="card muted">{t("rv_none")}</div> : (
        <>
          <div className="card prow">
            <div className="info"><span className="rating-big">{d.rating_avg.toFixed(1)}</span> <Stars value={d.rating_avg} /></div>
            <div className="note">{d.rating_count} {t("rv_count")}</div>
          </div>
          {d.reviews.map((r) => (
            <div className="card stack review" key={r.id}>
              <div className="prow"><div className="info"><b>{r.author}</b> <span className="note">· {fmtDate(r.created_at, lang)}</span></div><Stars value={r.rating} size={16} /></div>
              {r.comment && <div>{r.comment}</div>}
            </div>
          ))}
        </>
      )}
    </>
  );
}
