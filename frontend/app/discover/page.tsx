"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, distanceLabel, type Discovery, type DiscoveredShop, isLoggedIn, type Profile, RADIUS_OPTIONS } from "@/lib/api";
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

  useEffect(() => {
    if (isLoggedIn()) api<Profile>("/customers/me").then((p) => setRadius(p.search_radius_km)).catch(() => {});
    getPosition().then(setCoords);
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
      setError(e instanceof ApiError && e.code === "location_required" ? t("needLocation") : t("genericError"));
    }
  }, [coords, radius, category, t]);

  useEffect(() => {
    if (coords === undefined) return;
    const id = setTimeout(() => load(0), category ? 300 : 0);
    return () => clearTimeout(id);
  }, [coords, radius, category, load]);

  async function toggleFavourite(shop: DiscoveredShop) {
    if (!isLoggedIn()) return router.push(`/login?next=${encodeURIComponent("/discover")}`);
    await api(`/customers/me/favourites/${shop.slug}`, { method: shop.is_favourite ? "DELETE" : "POST" });
    setItems((prev) => prev?.map((s) => (s.slug === shop.slug ? { ...s, is_favourite: !s.is_favourite } : s)) ?? null);
  }

  return (
    <main className="stack">
      <h1>{t("discover")}</h1>
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
        <input type="text" placeholder={t("categoryPlaceholder")} value={category} onChange={(e) => setCategory(e.target.value)} />
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

      {error && <div className="card error">{error}</div>}
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
              {s.distance_m !== null && <div className="dist">{distanceLabel(s.distance_m)} {t("away")}</div>}
            </div>
            <button className={`heart ${s.is_favourite ? "on" : ""}`} onClick={() => toggleFavourite(s)}
              aria-label={s.is_favourite ? t("inFavourites") : t("addFavourite")}>
              {s.is_favourite ? "♥" : "♡"}
            </button>
          </div>
        ))
      )}
      {hasMore && <button className="btn secondary" onClick={() => load(items?.length ?? 0)}>{t("loadMore")}</button>}
    </main>
  );
}
