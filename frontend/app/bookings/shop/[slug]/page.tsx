"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, isLoggedIn, rupees } from "@/lib/api";
import { type Booking, timeLeft } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";

type LimitedShop = {
  slug: string; shop_name: string; category: string; address_line: string; city: string; state: string | null;
  pincode: string; lat: number | null; lng: number | null; phone: string | null; whatsapp_url: string | null;
  timings: Record<string, string[][]>; live: boolean; bookings: Booking[];
};

/** SPEC 5 limited view: how to reach a shop where I have an open booking, even if its plan expired. No products. */
export default function LimitedShopPage() {
  const { t, day } = useI18n();
  const router = useRouter();
  const { slug } = useParams<{ slug: string }>();
  const [shop, setShop] = useState<LimitedShop | null>(null);
  const [gone, setGone] = useState(false);
  const now = Date.now();

  useEffect(() => {
    if (!isLoggedIn()) { router.replace(`/login?next=/bookings/shop/${slug}`); return; }
    api<LimitedShop>(`/bookings/shops/${encodeURIComponent(slug)}`).then(setShop)
      .catch(() => setGone(true)); // 404 once the booking is closed
  }, [router, slug]);

  if (gone) return <main className="stack"><div className="card">{t("shopNotFound")}</div><Link className="btn secondary" href="/bookings">{t("b_title")}</Link></main>;
  if (!shop) return <main><div className="card">{t("loading")}</div></main>;
  const map = shop.lat !== null && shop.lng !== null ? `https://www.google.com/maps/search/?api=1&query=${shop.lat},${shop.lng}` : null;

  return (
    <main className="stack">
      <div className="card stack">
        <div>
          <h1>{shop.shop_name}</h1>
          <div className="muted">{shop.category} · <span className="cap">{shop.city}</span></div>
        </div>
        {!shop.live && <div className="banner info">{t("lv_notice")}</div>}
        <div>
          <div className="muted">{t("address")}</div>
          <div>{shop.address_line}, <span className="cap">{shop.city}</span> {shop.pincode}</div>
        </div>
        <div className="row">
          {shop.whatsapp_url && <a className="btn wa" href={shop.whatsapp_url} target="_blank" rel="noopener noreferrer">{t("chatWhatsApp")}</a>}
          {shop.phone && <a className="btn secondary" href={`tel:${shop.phone}`}>{t("call")}</a>}
        </div>
        {map && <a className="btn secondary" href={map} target="_blank" rel="noopener noreferrer">📍 {t("lv_map")}</a>}
        {Object.keys(shop.timings).length > 0 && (
          <div>
            <div className="muted">{t("timings")}</div>
            {Object.entries(shop.timings).map(([d, ranges]) => (
              <div key={d}>{day(d)}: {ranges.map((r) => r.join("–")).join(", ")}</div>
            ))}
          </div>
        )}
      </div>
      <h2>{t("lv_bookings")}</h2>
      {shop.bookings.map((b) => (
        <div className="card stack" key={b.id}>
          <div className="pname">{b.product_name}</div>
          <div className="booking-no">{b.booking_no}</div>
          <div className="note">
            {t("b_points")}: <b>{rupees(b.discount_paise)}</b> · {t("b_timeLeft")}: <span className="countdown">{timeLeft(b.expires_at, now)}</span>
          </div>
        </div>
      ))}
      <Link className="btn" href="/bookings">{t("lv_goBookings")}</Link>
    </main>
  );
}
