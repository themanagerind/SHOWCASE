"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, type Profile, saveTokens } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { type Lang, messages } from "@/lib/messages";
import { readPrefill } from "@/lib/prefill";
import { errorKey } from "@/lib/errors";
import { safeNext } from "@/lib/safe-next";

function Login() {
  const { t, setLang } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const loggedOut = params.get("reason") === "logged_out";
  const [phone, setPhone] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromTM, setFromTM] = useState(false);
  // Arriving from THE-MANAGER "Shop Now": the number is filled in (still editable); OTP is always required.
  useEffect(() => {
    const p = next.startsWith("/welcome") ? readPrefill() : null;
    if (p) { setPhone(p.mobile.replace(/^\+91/, "")); setFromTM(true); }
  }, [next]);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(t(errorKey(e)));
    } finally {
      setBusy(false);
    }
  }

  const sendOtp = () =>
    run(async () => {
      const r = await api<{ phone: string }>("/auth/otp/request", { method: "POST", body: JSON.stringify({ phone }) });
      setSentTo(r.phone);
    });

  const verify = () =>
    run(async () => {
      const r = await api<{ access_token: string; refresh_token: string }>("/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({ phone: sentTo, code }),
      });
      saveTokens(r.access_token, r.refresh_token);
      // Use the language saved in the profile on this device too (deep audit B7).
      const p = await api<Profile>("/customers/me").catch(() => null);
      if (p?.profile_complete && p.preferred_language in messages) setLang(p.preferred_language as Lang);
      router.replace(next);
    });

  return (
    <main>
      <div className="card stack">
        <h1>{t("login")}</h1>
        {loggedOut && <div className="banner warn">{t("s_loggedOut")}</div>}
        {fromTM && !sentTo && <div className="banner info">{t("pf_loginHint")}</div>}
        {!sentTo ? (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); sendOtp(); }}>
            <div>
              <label htmlFor="phone">{t("phoneLabel")}</label>
              <input id="phone" type="tel" inputMode="numeric" autoComplete="tel" placeholder={t("phonePlaceholder")}
                value={phone} onChange={(e) => setPhone(e.target.value)} required />
            </div>
            <button className="btn" disabled={busy || phone.replace(/\D/g, "").length < 10}>{t("sendOtp")}</button>
          </form>
        ) : (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); verify(); }}>
            <div>
              <label htmlFor="otp">{t("otpLabel")} {sentTo}</label>
              <input id="otp" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
            </div>
            <button className="btn" disabled={busy || code.length < 4}>{t("verify")}</button>
            <button type="button" className="btn secondary" onClick={() => { setSentTo(null); setCode(""); }}>
              {t("changeNumber")}
            </button>
          </form>
        )}
        {error && <div className="error">{error}</div>}
      </div>
    </main>
  );
}

export default function LoginPage() {
  return <Suspense><Login /></Suspense>;
}
