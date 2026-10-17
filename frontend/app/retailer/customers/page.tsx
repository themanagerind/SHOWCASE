"use client";

import { useEffect, useState } from "react";
import RetailerNav from "@/components/RetailerNav";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useMyShop } from "@/lib/retailer";

type Row = {
  customer_id: string; name: string | null; phone: string; contact_consent: boolean;
  source: "LINK" | "QR" | "DISCOVERY"; is_favourite: boolean; joined_at: string;
};
type Page = { total: number; items: Row[] };
const PAGE = 50;

export default function CustomersPage() {
  const { t, lang } = useI18n();
  const { shop } = useMyShop();
  const [data, setData] = useState<Page | null>(null);

  const load = (offset: number) =>
    api<Page>(`/retailers/me/customers?limit=${PAGE}&offset=${offset}`).then((p) =>
      setData((prev) => (offset === 0 || !prev ? p : { total: p.total, items: [...prev.items, ...p.items] })));

  useEffect(() => { if (shop) load(0); }, [shop]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!shop || !data) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;
  const src = { LINK: t("viaLink"), QR: t("viaQr"), DISCOVERY: t("viaApp") };

  return (
    <main className="stack">
      <RetailerNav />
      <h1>{t("r_customersTitle")} ({data.total})</h1>
      {data.items.length === 0 ? (
        <div className="card muted">{t("r_noCustomers")}</div>
      ) : (
        data.items.map((c) => (
          <div className={`card prow ${c.is_favourite ? "" : "muted-row"}`} key={c.customer_id}>
            <div className="info">
              <div className="pname">{c.name ?? "—"}</div>
              <div>
                {c.contact_consent ? <a href={`tel:${c.phone}`}>{c.phone}</a> : <span>{c.phone}</span>}
                {!c.contact_consent && <span className="note"> · {t("r_phoneHidden")}</span>}
              </div>
              <div className="muted">
                {src[c.source]} · {new Date(c.joined_at).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", { timeZone: "Asia/Kolkata" })}
                {!c.is_favourite && ` · ${t("r_favNo")}`}
              </div>
            </div>
          </div>
        ))
      )}
      {data.items.length < data.total && (
        <button className="btn secondary" onClick={() => load(data.items.length)}>{t("loadMore")}</button>
      )}
    </main>
  );
}
