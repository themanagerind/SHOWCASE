"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, isLoggedIn } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { type PrefillRef, savePrefill } from "@/lib/prefill";

type Start = { status: "ok" | "invalid" | "expired" | "unavailable"; prefill_id: string | null; mobile: string | null };

/** Landing page of THE-MANAGER's "Shop Now" (SPEC 4.12). The token never stays in the address bar. */
export default function Welcome() {
  const { t } = useI18n();
  const router = useRouter();
  const [failed, setFailed] = useState<"expired" | "other" | null>(null);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return; // the token is single use: never send it twice (React strict mode)
    once.current = true;
    const token = new URLSearchParams(window.location.search).get("prefill");
    window.history.replaceState(null, "", "/welcome"); // keep it out of history, logs and Referer
    if (!token) { router.replace("/login"); return; }
    api<Start>("/prefill/start", { method: "POST", body: JSON.stringify({ token }) })
      .then((r) => {
        if (r.status !== "ok") { setFailed(r.status === "expired" ? "expired" : "other"); return; }
        savePrefill({ prefill_id: r.prefill_id, mobile: r.mobile } as PrefillRef);
        router.replace(isLoggedIn() ? "/welcome/details" : "/login?next=/welcome/details");
      })
      .catch(() => setFailed("other"));
  }, [router]);

  return (
    <main>
      <div className="card stack">
        <h1>{t("pf_title")}</h1>
        {!failed ? <div className="muted">{t("loading")}</div> : (
          <>
            <div className="banner warn">{t(failed === "expired" ? "pf_expired" : "pf_unavailable")}</div>
            <Link className="btn" href="/login?next=/profile">{t("pf_continue")}</Link>
          </>
        )}
      </div>
    </main>
  );
}
