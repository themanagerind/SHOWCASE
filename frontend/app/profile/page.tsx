"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError, clearTokens, isLoggedIn, type Profile, RADIUS_OPTIONS } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { LANGS, type Lang } from "@/lib/messages";

function ProfileForm() {
  const { t, lang, setLang } = useI18n();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [form, setForm] = useState({ name: "", pincode: "", city: "", preferred_language: "hi", contact_consent: false, search_radius_km: 5 });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent("/profile" + (next ? `?next=${encodeURIComponent(next)}` : ""))}`);
      return;
    }
    api<Profile>("/customers/me").then((p) => {
      setForm({
        name: p.name ?? "", pincode: p.pincode ?? "", city: p.city ?? "",
        // New users keep the language they are already using on screen.
        preferred_language: p.profile_complete ? p.preferred_language : lang, contact_consent: p.contact_consent,
        search_radius_km: p.search_radius_km,
      });
      setLoaded(true);
    });
  }, [router, next]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await api("/customers/me", { method: "PATCH", body: JSON.stringify(form) });
      setLang(form.preferred_language as Lang);
      if (next && next.startsWith("/") && !next.startsWith("//")) router.replace(next);
      else setMsg({ ok: true, text: t("saved") });
    } catch (err) {
      setMsg({ ok: false, text: err instanceof ApiError ? err.message : t("genericError") });
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return <main><div className="card">{t("loading")}</div></main>;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value });

  return (
    <main>
      <form className="card stack" onSubmit={save}>
        <h1>{t("profileTitle")}</h1>
        <div>
          <label htmlFor="name">{t("name")}</label>
          <input id="name" type="text" autoComplete="name" value={form.name} onChange={set("name")} required minLength={2} />
        </div>
        <div className="row">
          <div>
            <label htmlFor="pincode">{t("pincode")}</label>
            <input id="pincode" type="text" inputMode="numeric" maxLength={6} pattern="[1-9][0-9]{5}"
              autoComplete="postal-code" value={form.pincode} onChange={set("pincode")} required />
          </div>
          <div>
            <label htmlFor="city">{t("city")}</label>
            <input id="city" type="text" autoComplete="address-level2" value={form.city} onChange={set("city")} required />
          </div>
        </div>
        <div>
          <label htmlFor="lang">{t("language")}</label>
          <select id="lang" value={form.preferred_language} onChange={set("preferred_language")}>
            {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="radius">{t("radius")}</label>
          <select id="radius" value={form.search_radius_km}
            onChange={(e) => setForm({ ...form, search_radius_km: Number(e.target.value) })}>
            {RADIUS_OPTIONS.map((r) => <option key={r} value={r}>{r} {t("km")}</option>)}
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={form.contact_consent} onChange={set("contact_consent")} />
          <span>
            {t("consent")}
            <br />
            <span className="muted">{t("consentHelp")}</span>
          </span>
        </label>
        <button className="btn" disabled={busy}>{t("save")}</button>
        {msg && <div className={msg.ok ? "success" : "error"}>{msg.text}</div>}
        <a className="btn secondary" href="/retailer">🏪 {t("r_ownShopCta")}</a>
        <button type="button" className="btn secondary" onClick={() => { clearTokens(); location.href = "/"; }}>
          {t("logout")}
        </button>
      </form>
    </main>
  );
}

export default function ProfilePage() {
  return <Suspense><ProfileForm /></Suspense>;
}
