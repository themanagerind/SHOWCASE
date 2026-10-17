"use client";

import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import { type ProductInput, toPaise, toRupeesInput } from "@/lib/retailer";

type Props = {
  initial?: Partial<ProductInput>;
  submitLabel: string;
  lockedName?: boolean; // during the weekly lock the name cannot change
  onSubmit: (p: ProductInput) => Promise<void> | void;
  onCancel?: () => void;
};

export default function ProductForm({ initial, submitLabel, lockedName, onSubmit, onCancel }: Props) {
  const { t } = useI18n();
  const [f, setF] = useState({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    price: toRupeesInput(initial?.price_paise),
    mrp: toRupeesInput(initial?.mrp_paise),
    discount: toRupeesInput(initial?.wallet_discount_paise),
    stock: String(initial?.stock_qty ?? 1),
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const price = toPaise(f.price);
    const discount = toPaise(f.discount);
    const mrp = f.mrp.trim() ? toPaise(f.mrp) : null;
    if (!(price > 0) || !(discount > 0) || discount > price || (mrp !== null && Number.isNaN(mrp))) {
      setErr(t("r_errDiscount"));
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      await onSubmit({
        name: f.name.trim(), description: f.description.trim() || null, price_paise: price, mrp_paise: mrp,
        wallet_discount_paise: discount, stock_qty: Math.max(0, parseInt(f.stock || "0", 10) || 0),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div>
        <label htmlFor="pname">{t("r_productName")}</label>
        <input id="pname" type="text" value={f.name} onChange={set("name")} required minLength={2} disabled={lockedName} />
      </div>
      <div className="row">
        <div>
          <label htmlFor="price">{t("r_price")}</label>
          <input id="price" type="text" inputMode="decimal" value={f.price} onChange={set("price")} required />
        </div>
        <div>
          <label htmlFor="mrp">{t("r_mrp")}</label>
          <input id="mrp" type="text" inputMode="decimal" value={f.mrp} onChange={set("mrp")} />
        </div>
      </div>
      <div className="row">
        <div>
          <label htmlFor="discount">{t("r_discount")}</label>
          <input id="discount" type="text" inputMode="decimal" value={f.discount} onChange={set("discount")} required />
        </div>
        <div>
          <label htmlFor="stock">{t("r_stock")}</label>
          <input id="stock" type="text" inputMode="numeric" value={f.stock} onChange={set("stock")} />
        </div>
      </div>
      <div className="note">{t("r_discountHelp")}</div>
      <div>
        <label htmlFor="desc">{t("r_description")}</label>
        <textarea id="desc" rows={2} value={f.description} onChange={set("description")} />
      </div>
      {err && <div className="error">{err}</div>}
      <div className="row">
        {onCancel && <button type="button" className="btn secondary" onClick={onCancel}>{t("r_cancel")}</button>}
        <button className="btn" disabled={busy}>{submitLabel}</button>
      </div>
    </form>
  );
}
