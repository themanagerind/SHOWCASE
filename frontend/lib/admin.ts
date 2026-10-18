"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, isLoggedIn } from "./api";
import type { MySubscription } from "./subscription";

export type AdminRow = {
  id: string; slug: string; shop_name: string; city: string; phone: string; status: string | null;
  plan_code: string | null; billing_cycle: string | null; current_period_end: string | null; grace_ends_at: string | null;
};
export type Offer = {
  id: string; offer_type: "PERCENT" | "FIXED_DISCOUNT" | "CUSTOM_PRICE"; value: number; plan_code: string | null;
  billing_cycle: string | null; valid_from: string; valid_until: string; reason: string; revoked_at: string | null;
};
export type Audit = {
  id: string; created_at: string; admin_phone: string; retailer_id: string | null; action: string;
  old_value: Record<string, unknown> | null; new_value: Record<string, unknown> | null;
};
export type RetailerDetail = {
  retailer: AdminRow; subscription: MySubscription; price_override_paise: number | null;
  price_override_reason: string | null; grace_days: number; offers: Offer[]; audit: Audit[];
};
export type AdminPlan = { code: string; name: string; monthly_paise: number; yearly_paise: number; features: Record<string, unknown>; subscribers: number };

/** Redirects non-admins away; returns true once the caller is known to be an admin. */
export function useAdminGate(): boolean {
  const router = useRouter();
  const [ok, setOk] = useState(false);
  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login?next=/admin");
      return;
    }
    api<{ roles: string[] }>("/auth/me").then((me) => (me.roles.includes("admin") ? setOk(true) : router.replace("/")));
  }, [router]);
  return ok;
}

export const adminError = (e: unknown) =>
  e instanceof ApiError ? (e.code === "super_admin_only" ? "Only a SUPER_ADMIN can do this." : e.message) : "Something went wrong.";

export const dt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
