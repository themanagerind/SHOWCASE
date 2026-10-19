"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, isLoggedIn, type Profile } from "@/lib/api";
import { fill } from "@/lib/bookings";
import { errorKey } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { clearPrefill, type PrefillData, readPrefill } from "@/lib/prefill";

type Form = {
  name: string; society_name: string; flat_number: string; floor: string; address_line: string;
  city: string; state: string; pincode: string; contact_consent: boolean;
};
type Me = Profile & { society_name: string | null; address_line: string | null; flat_number: string | null; floor: string | null; state: string | null };

const FIELDS = ["name", "society_name", "flat_number", "floor", "address_line", "city", "state", "pincode"] as const;

/** After OTP: the prefilled profile form. Only EMPTY profile fields are filled; nothing is saved until "Save". */
export default function WelcomeDetails() {
  const { t } = useI18n();
  const router = useRouter();
  const [form, setForm] = useState<Form | null>(null);
  const [note, setNote] = useState<"filled" | "mismatch" | "expired" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return; // load once; a language switch must not wipe what the resident typed
    once.current = true;
    if (!isLoggedIn()) { router.replace("/login?next=/welcome/details"); return; }
    const ref = readPrefill();
    clearPrefill(); // single use on the server too
    (async () => {
      const me = await api<Me>("/customers/me");
      let data: PrefillData | null = null;
      if (ref) {
        try { data = await api<PrefillData>(`/prefill/${encodeURIComponent(ref.prefill_id)}`); setNote("filled"); }
        catch (e) { setNote(e instanceof ApiError && e.code === "prefill_phone_mismatch" ? "mismatch" : "expired"); }
      }
      const f = { contact_consent: me.contact_consent } as Form;
      for (const k of FIELDS) f[k] = (me[k] as string | null) || (data?.[k] ?? "") || "";
      setForm(f);
    })().catch(() => setError(t("genericError")));
  }, [router, t]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      await api("/customers/me", { method: "PATCH", body: JSON.stringify({ ...form, city: form.city.trim(), name: form.name.trim() }) });
      router.replace("/discover");
    } catch (err) {
      setError(t(errorKey(err)));
    } finally {
      setBusy(false);
    }
  }

  if (!form) return <main><div className="card">{error ?? t("loading")}</div></main>;
  const field = (k: (typeof FIELDS)[number], label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label key={k}>{label}<input type="text" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} {...extra} /></label>
  );

  return (
    <main>
      <form className="card stack" onSubmit={save}>
        <h1>{t("profileTitle")}</h1>
        {note === "filled" && <div className="banner info">{fill(t("pf_filled"), { save: t("save") })}</div>}
        {note === "mismatch" && <div className="banner warn">{t("pf_mismatch")}</div>}
        {note === "expired" && <div className="banner warn">{t("pf_expired")}</div>}
        {field("name", t("name"), { required: true, minLength: 2, maxLength: 120 })}
        {field("society_name", t("pf_society"), { maxLength: 120 })}
        <div className="row">
          {field("flat_number", t("pf_flat"), { maxLength: 20 })}
          {field("floor", t("pf_floor"), { maxLength: 10 })}
        </div>
        {field("address_line", t("address"), { maxLength: 200 })}
        <div className="row">
          {field("city", t("city"), { required: true, minLength: 2, maxLength: 80 })}
          {field("pincode", t("pincode"), { required: true, inputMode: "numeric", pattern: "[1-9][0-9]{5}", maxLength: 6 })}
        </div>
        {field("state", t("r_state"), { maxLength: 60 })}
        <label className="check">
          <input type="checkbox" checked={form.contact_consent} onChange={(e) => setForm({ ...form, contact_consent: e.target.checked })} />
          {t("consent")}
        </label>
        <div className="note">{t("consentHelp")}</div>
        <button className="btn" disabled={busy}>{t("save")}</button>
        {error && <div className="error">{error}</div>}
      </form>
    </main>
  );
}
