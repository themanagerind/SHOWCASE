"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import ProductForm from "@/components/ProductForm";
import RetailerNav from "@/components/RetailerNav";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { errorKey, type OwnProduct, type ProductInput, useMyShop } from "@/lib/retailer";

export default function EditProduct() {
  const { t } = useI18n();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { shop } = useMyShop();
  const [product, setProduct] = useState<OwnProduct | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!shop) return;
    api<OwnProduct[]>("/retailers/me/products").then((all) => setProduct(all.find((p) => p.id === id) ?? null));
  }, [shop, id]);

  if (!shop || !product) return <main><RetailerNav /><div className="card">{t("loading")}</div></main>;
  const locked = !!shop.products_locked_until;

  async function save(p: ProductInput) {
    // Name cannot change while the product set is locked (SPEC 4.3); send only what may change.
    const body: Partial<ProductInput> = { ...p };
    if (locked || p.name === product!.name) delete body.name;
    try {
      await api(`/retailers/me/products/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      router.push("/retailer/products");
    } catch (e) {
      setErr(t(errorKey(e)));
    }
  }

  return (
    <main className="stack">
      <RetailerNav />
      <div className="card stack">
        <h1>{t("r_edit")}: {product.name}</h1>
        {locked && <div className="banner warn">{t("r_lockedHelp")}</div>}
        {err && <div className="error">{err}</div>}
        <ProductForm initial={product} lockedName={locked} submitLabel={t("r_save")} onSubmit={save}
          onCancel={() => router.push("/retailer/products")} />
      </div>
    </main>
  );
}
