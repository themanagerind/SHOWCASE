"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ProductForm from "@/components/ProductForm";
import RetailerNav from "@/components/RetailerNav";
import { api, rupees } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { changeWillLock, errorKey, fmtDate, type OwnProduct, type ProductInput, useMyShop } from "@/lib/retailer";

export default function RetailerProducts() {
  const { t, lang } = useI18n();
  const { shop, reload } = useMyShop();
  const [items, setItems] = useState<OwnProduct[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [swapMode, setSwapMode] = useState(false);
  const [toRemove, setToRemove] = useState<Set<string>>(new Set());
  const [toAdd, setToAdd] = useState<ProductInput[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => setItems(await api<OwnProduct[]>("/retailers/me/products")), []);
  useEffect(() => { if (shop) load(); }, [shop, load]);

  async function run(fn: () => Promise<unknown>) {
    setMsg(null);
    try {
      await fn();
      await Promise.all([load(), reload()]);
      setMsg({ ok: true, text: t("saved") });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: t(errorKey(e)) });
      return false;
    }
  }

  if (!shop || !items) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;

  const active = items.filter((p) => p.is_active);
  const hidden = items.filter((p) => !p.is_active);
  const locked = !!shop.products_locked_until;
  const full = shop.max_products !== null && active.length >= shop.max_products;
  const confirmLock = (kind: "add" | "remove" | "swap") => !changeWillLock(shop, kind) || confirm(t("r_confirmLock"));

  async function add(p: ProductInput) {
    if (!confirmLock("add")) return;
    if (await run(() => api("/retailers/me/products", { method: "POST", body: JSON.stringify(p) }))) setAdding(false);
  }

  async function hide(id: string) {
    if (!confirmLock("remove")) return;
    await run(() => api(`/retailers/me/products/${id}`, { method: "DELETE" }));
  }

  async function doSwap() {
    if (!confirmLock("swap")) return;
    const ok = await run(() => api("/retailers/me/products/swap", {
      method: "POST", body: JSON.stringify({ remove: [...toRemove], add: toAdd }),
    }));
    if (ok) { setSwapMode(false); setToRemove(new Set()); setToAdd([]); }
  }

  return (
    <main className="stack">
      <RetailerNav />
      <div className="row" style={{ alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{t("r_products")}</h1>
        <div style={{ textAlign: "right" }} className="muted">
          {active.length} / {shop.max_products ?? t("r_unlimited")}
        </div>
      </div>

      {locked ? (
        <div className="banner warn">🔒 {t("r_lockedUntil")} <b>{fmtDate(shop.products_locked_until!, lang)}</b><br />{t("r_lockedHelp")}</div>
      ) : !shop.swap_locks ? (
        <div className="banner ok">{t("r_noLock")}</div>
      ) : shop.first_listing_free && !swapMode ? (
        <div className="banner ok">{t("r_firstListing")}</div>
      ) : (
        <div className="banner info">{t("r_lockWarn")}</div>
      )}
      {!shop.plan_code && <div className="banner warn">{t("r_noPlan")}</div>}
      {msg && <div className={msg.ok ? "success" : "banner warn"}>{msg.text}</div>}

      {!swapMode && !locked && shop.plan_code && (
        adding ? (
          <div className="card"><ProductForm submitLabel={t("r_save")} onSubmit={add} onCancel={() => setAdding(false)} /></div>
        ) : (
          <div className="row">
            {!full && <button className="btn" onClick={() => setAdding(true)}>+ {t("r_addProduct")}</button>}
            {active.length > 0 && <button className="btn secondary" onClick={() => setSwapMode(true)}>⇄ {t("r_swapMode")}</button>}
          </div>
        )
      )}

      {swapMode && <div className="banner info">{t("r_swapHelp")}</div>}

      {active.map((p) => (
        <div className="card prow" key={p.id}>
          {swapMode && (
            <input type="checkbox" aria-label={t("r_swapRemove")} style={{ width: 22, height: 22, accentColor: "var(--danger)" }}
              checked={toRemove.has(p.id)}
              onChange={(e) => {
                const next = new Set(toRemove);
                if (e.target.checked) next.add(p.id); else next.delete(p.id);
                setToRemove(next);
              }} />
          )}
          <div className="info">
            <div className="pname">{p.name}</div>
            <div>
              <span className="price">{rupees(p.price_paise)}</span>
              {p.mrp_paise && p.mrp_paise > p.price_paise && <span className="mrp">{rupees(p.mrp_paise)}</span>}
            </div>
            <span className="badge">{t("walletDiscount")}: {rupees(p.wallet_discount_paise)}</span>
            <span className="muted" style={{ marginLeft: 8, fontSize: 13 }}>{t("r_stock")}: {p.stock_qty}</span>
          </div>
          {!swapMode && (
            <div className="actions">
              <Link className="small-btn" href={`/retailer/products/${p.id}`}>{t("r_edit")}</Link>
              {!locked && <button className="small-btn danger" onClick={() => hide(p.id)}>{t("r_hide")}</button>}
            </div>
          )}
        </div>
      ))}

      {swapMode && (
        <div className="card stack">
          <h2>{t("r_swapNew")} ({toAdd.length})</h2>
          {toAdd.map((p, i) => (
            <div key={i} className="prow">
              <div className="info"><b>{p.name}</b> · {rupees(p.price_paise)}</div>
              <button className="small-btn danger" onClick={() => setToAdd(toAdd.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <ProductForm key={toAdd.length} submitLabel={`+ ${t("r_addToSwap")}`} onSubmit={(p) => setToAdd([...toAdd, p])} />
          <div className="row">
            <button className="btn secondary" onClick={() => { setSwapMode(false); setToRemove(new Set()); setToAdd([]); }}>{t("r_cancel")}</button>
            <button className="btn" disabled={toRemove.size === 0 && toAdd.length === 0} onClick={doSwap}>
              {t("r_swapConfirm")} (−{toRemove.size} / +{toAdd.length})
            </button>
          </div>
        </div>
      )}

      {hidden.length > 0 && (
        <>
          <h2>{t("r_hidden")} ({hidden.length})</h2>
          {hidden.map((p) => (
            <div className="card prow muted-row" key={p.id}>
              <div className="info"><div className="pname">{p.name}</div><span className="price">{rupees(p.price_paise)}</span></div>
            </div>
          ))}
        </>
      )}
    </main>
  );
}
