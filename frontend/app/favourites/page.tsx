"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, isLoggedIn, type Favourite } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function Favourites() {
  const { t } = useI18n();
  const router = useRouter();
  const joined = useSearchParams().get("joined");
  const [items, setItems] = useState<Favourite[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/favourites");
      return;
    }
    api<Favourite[]>("/customers/me/favourites").then(setItems, () => setFailed(true));
  }, [router]);

  async function remove(slug: string) {
    if (busy) return;
    setBusy(slug);
    try {
      await api(`/customers/me/favourites/${slug}`, { method: "DELETE" });
      setItems((prev) => prev?.filter((f) => f.slug !== slug) ?? null);
    } catch {
      alert(t("genericError"));
    } finally {
      setBusy(null);
    }
  }

  const sourceLabel = { LINK: t("viaLink"), QR: t("viaQr"), DISCOVERY: t("viaApp") };

  return (
    <main className="stack">
      <h1>{t("favourites")}</h1>
      {joined && <div className="success">{t("joinedShop")}</div>}
      {items === null ? (
        failed ? (
          <div className="card error stack" role="alert">{t("loadError")}
            <button className="btn secondary" onClick={() => location.reload()}>{t("retry")}</button></div>
        ) : <div className="card">{t("loading")}</div>
      ) : items.length === 0 ? (
        <div className="card muted">{t("noFavourites")}</div>
      ) : (
        items.map((f) => (
          <div className={`card fav ${f.available ? "" : "unavailable"}`} key={f.slug}>
            {f.photo ? <img className="thumb" src={f.photo} alt="" loading="lazy" /> : <div className="thumb" />}
            <div className="info">
              {f.available ? <Link href={`/${f.slug}`}>{f.shop_name}</Link>
                : f.limited_view ? <Link href={`/bookings/shop/${f.slug}`}>{f.shop_name}</Link>
                : <span className="pname">{f.shop_name}</span>}
              <div className="muted">{f.category} · <span className="cap">{f.city}</span> · {sourceLabel[f.source]}</div>
              {!f.available && <div className="note">{t(f.limited_view ? "f_openBooking" : "f_unavailable")}</div>}
            </div>
            <button className="linkbtn" onClick={() => remove(f.slug)} disabled={busy === f.slug}>{t("remove")}</button>
          </div>
        ))
      )}
    </main>
  );
}

export default function FavouritesPage() {
  return <Suspense><Favourites /></Suspense>;
}
