"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, isLoggedIn, rupees, type Product, type Storefront } from "@/lib/api";
import { bookingErrorKey, fill } from "@/lib/bookings";
import ShopReviews from "@/components/ShopReviews";
import { useI18n } from "@/lib/i18n";
import { track } from "@/lib/track";

export default function ShopView({ data, slug, source }: { data: Storefront | null; slug: string; source: "LINK" | "QR" }) {
  const { t, day } = useI18n();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<{ id: string; text: string } | null>(null);

  async function reserve(p: Product) {
    if (!isLoggedIn()) { router.push(`/login?next=/${slug}`); return; }
    if (!confirm(fill(t("b_confirmReserve"), { name: p.name, points: rupees(p.wallet_discount_paise) }))) return;
    setBusy(p.id);
    setErr(null);
    try {
      await api("/bookings", { method: "POST", body: JSON.stringify({ product_id: p.id }) });
      router.push("/bookings?new=1");
    } catch (e) {
      setErr({ id: p.id, text: t(bookingErrorKey(e)) });
    } finally {
      setBusy(null);
    }
  }

  // Analytics (SPEC 4.9): one shop_view per visit; a product counts as "seen" when half its card is on screen.
  const seen = useRef(new Set<string>());
  useEffect(() => {
    if (!data) return;
    track(slug, "shop_view");
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      const id = (e.target as HTMLElement).dataset.pid;
      if (e.isIntersecting && id && !seen.current.has(id)) { seen.current.add(id); track(slug, "product_view", id); }
    }), { threshold: 0.5 });
    document.querySelectorAll<HTMLElement>(".product[data-pid]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [data, slug]);

  if (!data) {
    return (
      <main>
        <div className="card">{t("shopNotFound")}</div>
      </main>
    );
  }
  const { shop, products } = data;
  const joinHref = `/${slug}/join?src=${source.toLowerCase()}`;

  return (
    <main className="stack">
      {shop.photos[0] && <img className="cover" src={shop.photos[0]} alt={shop.shop_name} />}
      <div className="card stack">
        <div>
          <h1>{shop.shop_name}</h1>
          <div className="muted">
            {shop.category} · <span className="cap">{shop.city}</span>
            {shop.rating_count > 0 && ` · ★ ${shop.rating_avg.toFixed(1)} (${shop.rating_count})`}
          </div>
        </div>
        {shop.description && <p style={{ margin: 0 }}>{shop.description}</p>}
        <Link className="btn" href={joinHref}>{t("joinShop")}</Link>
        <div className="row">
          {shop.whatsapp_url && (
            <a className="btn wa" href={shop.whatsapp_url} target="_blank" rel="noopener noreferrer" onClick={() => track(slug, "whatsapp_click")}>
              {t("chatWhatsApp")}
            </a>
          )}
          {shop.phone && <a className="btn secondary" href={`tel:${shop.phone}`} onClick={() => track(slug, "call_click")}>{t("call")}</a>}
        </div>
        <div>
          <div className="muted">{t("address")}</div>
          <div>{shop.address_line}, <span className="cap">{shop.city}</span> {shop.pincode}</div>
        </div>
        {Object.keys(shop.timings).length > 0 && (
          <div>
            <div className="muted">{t("timings")}</div>
            {Object.entries(shop.timings).map(([d, ranges]) => (
              <div key={d}>
                {day(d)}: {ranges.map((r) => r.join("–")).join(", ")}
              </div>
            ))}
          </div>
        )}
      </div>

      <h2>{t("products")}</h2>
      {products.length === 0 ? (
        <div className="card muted">{t("noProducts")}</div>
      ) : (
        <div className="products">
          {products.map((p) => (
            <div className="product" key={p.id} data-pid={p.id}>
              {p.photos[0] ? <img src={p.photos[0]} alt={p.name} loading="lazy" /> : <div className="ph" />}
              <div className="body">
                <div className="name">{p.name}</div>
                <div>
                  <span className="price">{rupees(p.price_paise)}</span>
                  {p.mrp_paise && p.mrp_paise > p.price_paise && <span className="mrp">{rupees(p.mrp_paise)}</span>}
                </div>
                <span className="badge">{t("walletDiscount")}: {rupees(p.wallet_discount_paise)}</span>
                {p.stock_qty > 0 ? (
                  <button className="btn small" disabled={busy === p.id} onClick={() => reserve(p)}>{t("b_reserve")}</button>
                ) : (
                  <span className="muted note">{t("outOfStock")}</span>
                )}
                {err?.id === p.id && (
                  <div className="banner warn note">
                    {err.text}{" "}
                    {err.text === t("b_errPoints") && <Link href="/wallet">{t("w_nav")} →</Link>}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <ShopReviews slug={slug} />
    </main>
  );
}
