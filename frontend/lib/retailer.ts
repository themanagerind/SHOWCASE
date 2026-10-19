"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, isLoggedIn } from "./api";
import { errorKey as commonErrorKey } from "./errors";
import { intlLocale, type Lang, type MessageKey } from "./messages";

export type MyShop = {
  id: string;
  slug: string;
  shop_name: string;
  category: string;
  city: string;
  whatsapp_url: string | null;
  plan_code: string | null;
  subscription_status: string | null;
  plan_expired: boolean;
  products_locked_until: string | null;
  can_change_products_now: boolean;
  swap_locks: boolean;
  first_listing_free: boolean;
  active_products: number;
  max_products: number | null;
  customers_count: number;
  share_link: string;
  rating_avg: number;
  rating_count: number;
};

export type OwnProduct = {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  price_paise: number;
  mrp_paise: number | null;
  wallet_discount_paise: number;
  stock_qty: number;
  photos: string[];
  is_active: boolean;
};

export type ProductInput = {
  name: string;
  description?: string | null;
  price_paise: number;
  mrp_paise?: number | null;
  wallet_discount_paise: number;
  stock_qty: number;
};

/** Loads the signed-in retailer's shop; sends to login / shop setup when needed. */
export function useMyShop() {
  const router = useRouter();
  const [shop, setShop] = useState<MyShop | null>(null);
  const [failed, setFailed] = useState(false);

  const reload = useCallback(async () => {
    try {
      setShop(await api<MyShop>("/retailers/me"));
      setFailed(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === "no_shop") router.replace("/retailer/setup");
      else if (e instanceof ApiError && e.status === 401) router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      else setFailed(true);
    }
  }, [router]);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`); // back to this page (deep audit B6)
      return;
    }
    reload();
  }, [reload, router]);

  return { shop, reload, failed };
}

/** "2,899.50" / "2899.5" → 289950 paise. Returns NaN for invalid input. */
export function toPaise(rupees: string): number {
  const clean = rupees.replace(/,/g, "").trim();
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return NaN;
  const [whole, frac = ""] = clean.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}

export const toRupeesInput = (paise: number | null | undefined) =>
  paise == null ? "" : (paise / 100).toString();

/** Does the next add / hide / swap start the 7-day lock? */
export const changeWillLock = (shop: MyShop, kind: "add" | "remove" | "swap") =>
  shop.swap_locks && !(kind === "add" && shop.first_listing_free);

export function errorKey(e: unknown): MessageKey {
  if (!(e instanceof ApiError)) return "genericError";
  return (
    ({
      product_limit: "r_errLimit",
      weekly_lock: "r_errLock",
      subscription_required: "r_errPlan",
      invalid_discount: "r_errDiscount",
    } as Record<string, MessageKey>)[e.code] ?? commonErrorKey(e)
  );
}

export const fmtDate = (iso: string, lang: Lang) =>
  new Date(iso).toLocaleString(intlLocale(lang), {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit",
  });
