"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PlanLocked from "@/components/PlanLocked";
import RetailerNav from "@/components/RetailerNav";
import { api } from "@/lib/api";
import { fill } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";
import { intlLocale } from "@/lib/messages";
import { useMyShop } from "@/lib/retailer";

type Day = { date: string; visitors: number; views: number };
type Dash = {
  full: boolean; days: number; views_7d: number; daily: Day[]; visitors: number; new_visitors: number; returning_visitors: number;
  shop_views: number; whatsapp_clicks: number; call_clicks: number; favourites: number; bookings_started: number;
  bookings_confirmed: number; top_products: { product_id: string; name: string; views: number }[];
};

/** Retailer insights (SPEC 4.9). One series per chart, one hue (brand green); values in text tokens. */
export default function Insights() {
  const { t, lang } = useI18n();
  const { shop } = useMyShop();
  const [days, setDays] = useState(30);
  const [d, setD] = useState<Dash | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => { if (shop?.plan_code) api<Dash>(`/retailers/me/analytics?days=${days}`).then(setD); }, [shop, days]);

  if (shop && !shop.plan_code) return <PlanLocked />;
  if (!shop || !d) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;

  if (!d.full) {
    return (
      <main className="stack">
        <RetailerNav />
        <h1>{t("an_title")}</h1>
        <div className="card stack">
          <div className="teaser">{fill(t("an_teaser"), { n: d.views_7d })}</div>
          <div className="banner info">{t("an_upgrade")}</div>
          <Link className="btn" href="/retailer/plan">{t("p_seePlans")}</Link>
        </div>
      </main>
    );
  }

  const max = Math.max(1, ...d.daily.map((x) => x.visitors));
  const fmtDay = (iso: string, long = false) => new Date(`${iso}T00:00:00+05:30`).toLocaleDateString(intlLocale(lang),
    { timeZone: "Asia/Kolkata", day: "numeric", month: "short", ...(long ? { weekday: "short" } : {}) });
  const conv = d.bookings_started ? Math.round((d.bookings_confirmed * 100) / d.bookings_started) : null;
  const tiles: [string, number | string][] = [
    [t("an_visitors"), d.visitors], [t("an_views"), d.shop_views], [t("an_wa"), d.whatsapp_clicks],
    [t("an_call"), d.call_clicks], [t("an_fav"), d.favourites], [t("an_conversion"), conv === null ? "—" : `${conv}%`],
  ];
  const h = hover !== null ? d.daily[hover] : null;

  return (
    <main className="stack">
      <RetailerNav />
      <h1>{t("an_title")}</h1>
      <div className="tabs" role="tablist">
        {[7, 30, 90].map((n) => (
          <button key={n} role="tab" aria-selected={days === n} className={days === n ? "on" : ""} onClick={() => setDays(n)}>
            {fill(t("an_days"), { n })}
          </button>
        ))}
      </div>

      <div className="stats">
        {tiles.map(([label, value]) => (
          <div className="stat" key={label}><div className="num">{value}</div><div className="lbl">{label}</div></div>
        ))}
      </div>

      <div className="card stack">
        <h2>{t("an_dailyTitle")}</h2>
        {d.visitors === 0 ? <div className="muted">{t("an_noData")}</div> : (
          <>
            <div className="note chart-tip" aria-live="polite">
              {h ? <><b>{fmtDay(h.date, true)}</b> · {h.visitors} {t("an_visitors").toLowerCase()} · {h.views} {t("an_views").toLowerCase()}</> : " "}
            </div>
            <div className="bars" onMouseLeave={() => setHover(null)}>
              <div className="bars-axis"><span>{max}</span><span>0</span></div>
              <div className="bars-plot" style={{ ["--n" as string]: d.daily.length }}>
                {d.daily.map((x, i) => (
                  <button key={x.date} type="button" className={`bar-slot ${hover === i ? "on" : ""}`}
                    aria-label={`${fmtDay(x.date)}: ${x.visitors}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
                    onClick={() => setHover(i)}>
                    <span className="bar" style={{ height: `${(x.visitors / max) * 100}%` }} />
                  </button>
                ))}
              </div>
            </div>
            <div className="bars-x note"><span>{fmtDay(d.daily[0].date)}</span><span>{fmtDay(d.daily[d.daily.length - 1].date)}</span></div>
            <details>
              <summary className="note">{t("an_table")}</summary>
              <table className="data-table">
                <thead><tr><th>{t("an_date")}</th><th>{t("an_visitors")}</th><th>{t("an_views")}</th></tr></thead>
                <tbody>{[...d.daily].reverse().map((x) => <tr key={x.date}><td>{fmtDay(x.date)}</td><td>{x.visitors}</td><td>{x.views}</td></tr>)}</tbody>
              </table>
            </details>
          </>
        )}
      </div>

      <div className="card stack">
        <h2>{t("an_visitorsTitle")}</h2>
        <div className="split-row"><span>{t("an_new")}</span><b>{d.new_visitors}</b></div>
        <div className="split-row"><span>{t("an_returning")}</span><b>{d.returning_visitors}</b></div>
      </div>

      <div className="card stack">
        <h2>{t("an_bookingsTitle")}</h2>
        <div className="split-row"><span>{t("an_bookStart")}</span><b>{d.bookings_started}</b></div>
        <div className="split-row"><span>{t("an_bookDone")}</span><b>{d.bookings_confirmed}</b></div>
      </div>

      <div className="card stack">
        <h2>{t("an_top")}</h2>
        {d.top_products.length === 0 ? <div className="muted">{t("an_noData")}</div> : d.top_products.map((p) => (
          <div key={p.product_id} className="top-row">
            <div className="split-row"><span>{p.name}</span><b>{p.views}</b></div>
            <div className="bar-h"><span style={{ width: `${(p.views / d.top_products[0].views) * 100}%` }} /></div>
          </div>
        ))}
      </div>
    </main>
  );
}
