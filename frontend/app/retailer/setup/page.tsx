"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, isLoggedIn } from "@/lib/api";
import { errorKey } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

const slugify = (s: string) =>
  s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);

export default function ShopSetupPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [f, setF] = useState({
    shop_name: "", slug: "", category: "", address_line: "", city: "", state: "", pincode: "",
    phone: "", whatsapp_number: "", upi_id: "", payment_link: "",
  });
  const [slugTouched, setSlugTouched] = useState(false);
  const [loc, setLoc] = useState<{ lat: number; lng: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/retailer/setup");
      return;
    }
    // Already has a shop → dashboard.
    api("/retailers/me").then(() => router.replace("/retailer")).catch(() => {});
  }, [router]);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setF((prev) => ({
      ...prev,
      [k]: v,
      ...(k === "shop_name" && !slugTouched ? { slug: slugify(v) } : {}),
    }));
  };

  function useMyLocation() {
    navigator.geolocation?.getCurrentPosition(
      (p) => setLoc({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => setErr(t("r_locationNeeded")),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!loc) {
      setErr(t("r_locationNeeded"));
      return;
    }
    setBusy(true);
    setErr(null);
    const body: Record<string, unknown> = { ...f, lat: loc.lat, lng: loc.lng };
    for (const k of ["state", "phone", "whatsapp_number", "upi_id", "payment_link"]) if (!body[k]) delete body[k];
    try {
      await api("/retailers", { method: "POST", body: JSON.stringify(body) });
      router.replace("/retailer");
    } catch (e2) {
      setErr(t(errorKey(e2)));
    } finally {
      setBusy(false);
    }
  }

  const field = (k: keyof typeof f, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div>
      <label htmlFor={k}>{label}</label>
      <input id={k} type="text" value={f[k]} onChange={set(k)} {...props} />
    </div>
  );

  return (
    <main>
      <form className="card stack" onSubmit={submit}>
        <h1>{t("r_setupTitle")}</h1>
        {field("shop_name", t("r_shopName"), { required: true, minLength: 2 })}
        <div>
          <label htmlFor="slug">{t("r_link")}</label>
          <input id="slug" type="text" value={f.slug} required minLength={3} pattern="[a-z0-9][a-z0-9\-]{1,58}[a-z0-9]"
            onChange={(e) => { setSlugTouched(true); setF({ ...f, slug: e.target.value.toLowerCase() }); }} />
          <div className="note">{t("r_linkHelp")}{f.slug || "…"}</div>
        </div>
        {field("category", t("r_category"), { required: true, placeholder: "Electronics" })}
        {field("address_line", t("r_address"), { required: true, autoComplete: "street-address" })}
        <div className="row">
          {field("pincode", t("pincode"), { required: true, inputMode: "numeric", maxLength: 6, pattern: "[1-9][0-9]{5}" })}
          {field("city", t("city"), { required: true })}
        </div>
        {field("state", t("r_state"))}
        <div className="row">
          {field("phone", t("r_phone"), { inputMode: "tel" })}
          {field("whatsapp_number", t("r_whatsapp"), { inputMode: "tel" })}
        </div>
        {field("upi_id", t("r_upi"), { placeholder: "name@okicici" })}
        {field("payment_link", t("r_paymentLink"), { type: "url", placeholder: "https://" })}
        <div>
          <label>{t("r_location")}</label>
          {loc ? (
            <div className="banner ok">📍 {t("r_locationSet")} ({loc.lat.toFixed(4)}, {loc.lng.toFixed(4)})</div>
          ) : (
            <button type="button" className="btn secondary" onClick={useMyLocation}>📍 {t("r_useLocation")}</button>
          )}
        </div>
        {err && <div className="error">{err}</div>}
        <button className="btn" disabled={busy}>{t("r_create")}</button>
      </form>
    </main>
  );
}
