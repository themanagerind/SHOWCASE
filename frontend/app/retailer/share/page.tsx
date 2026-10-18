"use client";

import { useEffect, useState } from "react";
import PlanLocked from "@/components/PlanLocked";
import RetailerNav from "@/components/RetailerNav";
import { api, API_URL } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useMyShop } from "@/lib/retailer";

type Share = { link: string; qr_link: string; whatsapp_share_url: string };

export default function SharePage() {
  const { t } = useI18n();
  const { shop } = useMyShop();
  const [share, setShare] = useState<Share | null>(null);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!shop?.plan_code) return;
    api<Share>("/retailers/me/share").then(setShare);
    // The QR endpoint needs the auth header, so fetch it as a blob instead of a plain <img src>.
    let url: string | null = null;
    fetch(`${API_URL}/retailers/me/qr`, { headers: { Authorization: `Bearer ${localStorage.getItem("showcase.access")}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b) { url = URL.createObjectURL(b); setQrUrl(url); } });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [shop]);

  if (shop && !shop.plan_code) return <PlanLocked />;
  if (!shop || !share) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;

  return (
    <main className="stack">
      <RetailerNav />
      <div className="card stack">
        <h1>{t("r_shareTitle")}</h1>
        <p className="muted" style={{ margin: 0 }}>{t("r_shareHelp")}</p>
        <div className="linkbox">
          <input type="text" readOnly value={share.link} onFocus={(e) => e.target.select()} />
        </div>
        <div className="row">
          <button className="btn secondary" onClick={async () => {
            try { await navigator.clipboard.writeText(share.link); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch {}
          }}>{copied ? t("r_copied") : t("r_copy")}</button>
          <a className="btn wa" href={share.whatsapp_share_url} target="_blank" rel="noopener noreferrer">{t("r_shareWa")}</a>
        </div>
      </div>
      <div className="card stack" style={{ textAlign: "center" }}>
        {qrUrl ? <img className="qr" src={qrUrl} alt="QR" /> : <div className="qr" />}
        <div className="muted">{t("r_qrHelp")}</div>
        {qrUrl && <a className="btn" href={qrUrl} download={`${shop.slug}-qr.png`}>{t("r_downloadQr")}</a>}
      </div>
    </main>
  );
}
