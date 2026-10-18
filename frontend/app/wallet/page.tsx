"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, isLoggedIn, rupees } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { intlLocale, type MessageKey } from "@/lib/messages";

type Entry = { id: string; created_at: string; entry_type: string; amount_paise: number; balance_after_paise: number; note: string | null };
type Wallet = { balance_paise: number; entries: Entry[] };
type Redeem = { status: "CREDITED" | "PENDING" | "REJECTED" | "ERROR"; amount_paise: number | null; balance_paise: number; error_code: string | null };

export default function WalletPage() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const [w, setW] = useState<Wallet | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => api<Wallet>("/wallet/me").then(setW), []);
  useEffect(() => {
    if (!isLoggedIn()) { router.replace("/login?next=/wallet"); return; }
    load();
  }, [router, load]);

  async function redeem(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<Redeem>("/wallet/me/redeem", { method: "POST", body: JSON.stringify({ code }) });
      if (r.status === "CREDITED") { setMsg({ ok: true, text: t("w_credited").replace("{amount}", rupees(r.amount_paise!)) }); setCode(""); }
      else if (r.status === "PENDING") setMsg({ ok: true, text: t("w_pending") });
      else if (r.error_code === "code_already_used") setMsg({ ok: false, text: t("w_used") });
      else if (r.status === "REJECTED") setMsg({ ok: false, text: t("w_invalid") });
      else setMsg({ ok: false, text: t("w_unavailable") });
      await load();
    } catch (err) {
      const c = err instanceof ApiError ? err.code : "";
      setMsg({ ok: false, text: t(c === "code_already_used" ? "w_used" : c === "invalid_code_format" ? "w_invalid" : c === "rate_limited" ? "genericError" : "w_unavailable") });
    } finally {
      setBusy(false);
    }
  }

  if (!w) return <main><div className="card">{t("loading")}</div></main>;
  return (
    <main className="stack">
      <h1>{t("w_title")}</h1>
      <div className="card wallet-hero">
        <div className="muted">{t("w_balance")}</div>
        <div className="wallet-amount">{rupees(w.balance_paise)}</div>
        <div className="note">{t("w_pointsNote")}</div>
      </div>
      <form className="card stack" onSubmit={redeem}>
        <h2>{t("w_redeemTitle")}</h2>
        <input type="text" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder={t("w_codePlaceholder")}
          autoCapitalize="characters" autoComplete="off" maxLength={20} className="code-input" required />
        <button className="btn" disabled={busy || code.replace(/\s/g, "").length < 6}>{t("w_redeem")}</button>
        {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}
      </form>
      <h2>{t("w_history")}</h2>
      {w.entries.length === 0 ? <div className="card muted">{t("w_empty")}</div> : w.entries.map((e) => (
        <div className="card prow" key={e.id}>
          <div className="info">
            <div className="pname">{t(`w_e_${e.entry_type}` as MessageKey)}</div>
            <div className="note">{new Date(e.created_at).toLocaleString(intlLocale(lang), { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</div>
          </div>
          <div className={`amount ${e.amount_paise > 0 ? "plus" : e.amount_paise < 0 ? "minus" : ""}`}>
            {e.amount_paise > 0 ? "+" : e.amount_paise < 0 ? "−" : ""}{rupees(Math.abs(e.amount_paise))}
          </div>
        </div>
      ))}
    </main>
  );
}
