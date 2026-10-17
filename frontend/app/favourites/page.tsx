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

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/favourites");
      return;
    }
    api<Favourite[]>("/customers/me/favourites").then(setItems).catch(() => setItems([]));
  }, [router]);

  async function remove(slug: string) {
    await api(`/customers/me/favourites/${slug}`, { method: "DELETE" });
    setItems((prev) => prev?.filter((f) => f.slug !== slug) ?? null);
  }

  const sourceLabel = { LINK: t("viaLink"), QR: t("viaQr"), DISCOVERY: t("viaApp") };

  return (
    <main className="stack">
      <h1>{t("favourites")}</h1>
      {joined && <div className="success">{t("joinedShop")}</div>}
      {items === null ? (
        <div className="card">{t("loading")}</div>
      ) : items.length === 0 ? (
        <div className="card muted">{t("noFavourites")}</div>
      ) : (
        items.map((f) => (
          <div className="card fav" key={f.slug}>
            {f.photo ? <img className="thumb" src={f.photo} alt="" loading="lazy" /> : <div className="thumb" />}
            <div className="info">
              <Link href={`/${f.slug}`}>{f.shop_name}</Link>
              <div className="muted">{f.category} · <span className="cap">{f.city}</span> · {sourceLabel[f.source]}</div>
            </div>
            <button className="linkbtn" onClick={() => remove(f.slug)}>{t("remove")}</button>
          </div>
        ))
      )}
    </main>
  );
}

export default function FavouritesPage() {
  return <Suspense><Favourites /></Suspense>;
}
