"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  api, ApiError, distanceLabel, type Discovery, type DiscoveredShop, type FoundProduct, isLoggedIn, type Profile,
  type ProductSearch, RADIUS_OPTIONS, rupees,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Coords = { lat: number; lng: number } | null;
const PAGE = 20;

function getPosition(): Promise<Coords> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    );
  });
}

export default function DiscoverPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [coords, setCoords] = useState<Coords | undefined>(undefined); // undefined = still asking
  const [radius, setRadius] = useState<number>(5);
  const [category, setCategory] = useState("");
  const [items, setItems] = useState<DiscoveredShop[] | null>(null);
  const [usedLocation, setUsedLocation] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"shops" | "products">("shops");
  const [term, setTerm] = useState("");
  const [products, setProducts] = useState<FoundProduct[] | null>(null);
  const [productsFailed, setProductsFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [favBusy, setFavBusy] = useState<string | null>(null);

  useEffect(() => {
    if (isLoggedIn()) api<Profile>("/customers/me").then((p) => setRadius(p.search_radius_km)).catch(() => {});
    // An unanswered location prompt never resolves: after 4 s show shops by pincode/city, then switch to the
    // position if it arrives later (deep audit B3).
    const fallback = setTimeout(() => setCoords((c) => (c === undefined ? null : c)), 4000);
    getPosition().then((p) => { clearTimeout(fallback); setCoords((c) => p ?? (c === undefined ? null : c)); });
    return () => clearTimeout(fallback);
  }, []);

  const load = useCallback(async (offset: number) => {
    const qs = new URLSearchParams({ radius_km: String(radius), limit: String(PAGE), offset: String(offset) });
    if (coords) { qs.set("lat", String(coords.lat)); qs.set("lng", String(coords.lng)); }
    if (category.trim()) qs.set("category", category.trim());
    try {
      const r = await api<Discovery>(`/discovery/shops?${qs}`);
      setError(null);
      setUsedLocation(r.used_location);
      setItems((prev) => (offset === 0 ? r.items : [...(prev ?? []), ...r.items]));
      setHasMore(r.items.length === PAGE);
    } catch (e) {
      setItems([]);
      setError(e instanceof ApiError && e.code === "location_required" ? t("needLocation") : t("loadError"));
    }
  }, [coords, radius, category, t]);

  useEffect(() => {
    if (coords === undefined) return;
    const id = setTimeout(() => load(0), category ? 300 : 0);
    return () => clearTimeout(id);
  }, [coords, radius, category, load]);

  useEffect(() => {
    if (tab !== "products" || coords === undefined) return;
    if (term.trim().length < 2) {
      setProducts(null);
      return;
    }
    const id = setTimeout(async () => {
      const qs = new URLSearchParams({ q: term.trim(), radius_km: String(radius) });
      if (coords) { qs.set("lat", String(coords.lat)); qs.set("lng", String(coords.lng)); }
      try {
        setProducts((await api<ProductSearch>(`/discovery/products?${qs}`)).items);
        setProductsFailed(false);
      } catch {
        setProducts(null);
        setProductsFailed(true);
      }
    }, 300);
    return () => clearTimeout(id);
  }, [tab, term, coords, radius, retryKey]);

  async function toggleFavourite(shop: DiscoveredShop) {
    if (!isLoggedIn()) return router.push(`/login?next=${encodeURIComponent("/discover")}`);
    if (favBusy) return;
    setFavBusy(shop.slug);
    try {
      await api(`/customers/me/favourites/${shop.slug}`, { method: shop.is_favourite ? "DELETE" : "POST" });
      setItems((prev) => prev?.map((s) => (s.slug === shop.slug ? { ...s, is_favourite: !s.is_favourite } : s)) ?? null);
    } catch {
      setError(t("genericError"));
    } finally {
      setFavBusy(null);
    }
  }

  return (
    <main className="stack">
      <h1>{t("discover")}</h1>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "shops"} className={tab === "shops" ? "on" : ""} onClick={() => setTab("shops")}>
          {t("tabShops")}
        </button>
        <button role="tab" aria-selected={tab === "products"} className={tab === "products" ? "on" : ""} onClick={() => setTab("products")}>
          {t("tabProducts")}
        </button>
      </div>
      <div className="card stack">
        <div>
          <div className="muted" style={{ marginBottom: 6 }}>{t("radius")}</div>
          <div className="chips">
            {RADIUS_OPTIONS.map((r) => (
              <button key={r} className={`chip ${r === radius ? "on" : ""}`} onClick={() => setRadius(r)}>
                {r} {t("km")}
              </button>
            ))}
          </div>
        </div>
        {tab === "shops" ? (
          <input type="text" aria-label={t("categoryPlaceholder")} placeholder={t("categoryPlaceholder")} value={category} onChange={(e) => setCategory(e.target.value)} />
        ) : (
          <>
            <input type="search" aria-label={t("searchProducts")} placeholder={t("searchProducts")} value={term} onChange={(e) => setTerm(e.target.value)} autoFocus />
            <div className="note">{t("productSearchHint")}</div>
          </>
        )}
        {coords !== undefined && (
          <div className="note">
            {usedLocation ? `📍 ${t("usingLocation")}` : t("usingProfile")}
            {!usedLocation && (
              <> · <button className="linkbtn" style={{ color: "var(--navy)", padding: 0 }}
                onClick={() => getPosition().then(setCoords)}>{t("useMyLocation")}</button></>
            )}
          </div>
        )}
      </div>

      {tab === "products" ? (
        productsFailed ? (
          <div className="card error stack">{t("loadError")}
            <button className="btn secondary" onClick={() => setRetryKey((k) => k + 1)}>{t("retry")}</button></div>
        ) : products === null ? null : products.length === 0 ? (
          <div className="card muted">{t("noProductsFound")}</div>
        ) : (
          products.map((p) => (
            <Link className="card fav plink" key={p.id} href={`/${p.shop_slug}`}>
              {p.photo ? <img className="thumb" src={p.photo} alt="" loading="lazy" /> : <div className="thumb" />}
              <div className="info">
                <div className="pname">{p.name}</div>
                <div>
                  <span className="price">{rupees(p.price_paise)}</span>
                  {p.mrp_paise && p.mrp_paise > p.price_paise && <span className="mrp">{rupees(p.mrp_paise)}</span>}
                </div>
                <span className="badge">{t("walletDiscount")}: {rupees(p.wallet_discount_paise)}</span>
                {!p.in_stock && <span className="badge out">{t("outOfStock")}</span>}
                <div className="muted">
                  {p.shop_name} · <span className="cap">{p.shop_city}</span>
                  {p.distance_m !== null && <> · <span className="dist">{distanceLabel(p.distance_m, { m: t("u_m"), km: t("km") })}</span></>}
                </div>
              </div>
            </Link>
          ))
        )
      ) : (
        <>
          {error && (
            <div className="card error stack">{error}
              <button className="btn secondary" onClick={() => load(0)}>{t("retry")}</button></div>
          )}
          {items === null ? (
            <div className="card">{t("loading")}</div>
          ) : items.length === 0 && !error ? (
            <div className="card muted">{t("noShopsNearby")}</div>
          ) : (
            items.map((s) => (
              <div className="card fav" key={s.slug}>
                {s.photo ? <img className="thumb" src={s.photo} alt="" loading="lazy" /> : <div className="thumb" />}
                <div className="info">
                  <Link href={`/${s.slug}`}>{s.shop_name}</Link>
                  <div className="muted">
                    {s.category} · <span className="cap">{s.city}</span>
                    {s.rating_count > 0 && ` · ★ ${s.rating_avg.toFixed(1)}`}
                  </div>
                  {s.distance_m !== null && <div className="dist">{distanceLabel(s.distance_m, { m: t("u_m"), km: t("km") })} {t("away")}</div>}
                </div>
                <button className={`heart ${s.is_favourite ? "on" : ""}`} onClick={() => toggleFavourite(s)} disabled={favBusy === s.slug}
                  aria-label={s.is_favourite ? t("inFavourites") : t("addFavourite")}>
                  {s.is_favourite ? "♥" : "♡"}
                </button>
              </div>
            ))
          )}
        </>
      )}
      {tab === "shops" && hasMore && <button className="btn secondary" onClick={() => load(items?.length ?? 0)}>{t("loadMore")}</button>}
    </main>
  );
}
