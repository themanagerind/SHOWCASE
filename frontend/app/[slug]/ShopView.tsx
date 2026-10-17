"use client";

import Link from "next/link";
import { rupees, type Storefront } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function ShopView({ data, slug, source }: { data: Storefront | null; slug: string; source: "LINK" | "QR" }) {
  const { t, day } = useI18n();
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
            <a className="btn wa" href={shop.whatsapp_url} target="_blank" rel="noopener noreferrer">
              {t("chatWhatsApp")}
            </a>
          )}
          {shop.phone && <a className="btn secondary" href={`tel:${shop.phone}`}>{t("call")}</a>}
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
            <div className="product" key={p.id}>
              {p.photos[0] ? <img src={p.photos[0]} alt={p.name} loading="lazy" /> : <div className="ph" />}
              <div className="body">
                <div className="name">{p.name}</div>
                <div>
                  <span className="price">{rupees(p.price_paise)}</span>
                  {p.mrp_paise && p.mrp_paise > p.price_paise && <span className="mrp">{rupees(p.mrp_paise)}</span>}
                </div>
                <span className="badge">{t("walletDiscount")}: {rupees(p.wallet_discount_paise)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
