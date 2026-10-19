import { ApiError } from "@/lib/api";
import type { MessageKey } from "@/lib/messages";

export type BookingStatus = "RESERVED" | "PURCHASED" | "FORFEITED" | "CANCELLED_BY_RETAILER";
export type Booking = {
  id: string; booking_no: string; product_id: string; product_name: string; price_paise: number; discount_paise: number;
  status: BookingStatus; created_at: string; expires_at: string; purchased_at: string | null; forfeited_at: string | null;
  cancelled_at: string | null; cancel_reason: string | null; shop_name: string | null; shop_slug: string | null;
  customer_name: string | null; customer_phone: string | null;
};
export type DiscountRequest = {
  id: string; amount_paise: number; note: string; status: "PENDING" | "CONFIRMED" | "DECLINED" | "EXPIRED";
  created_at: string; expires_at: string; responded_at: string | null; shop_name: string | null;
  customer_name: string | null; customer_phone: string | null;
};

/** "{name} …" placeholders in translated strings. */
export const fill = (s: string, vars: Record<string, string | number>) =>
  s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));

/** Time left until `iso`, e.g. "5h 12m" with fmt = t("u_hm") (never negative). */
export function timeLeft(iso: string, now: number, fmt = "{h}h {m}m"): string {
  const mins = Math.max(0, Math.floor((new Date(iso).getTime() - now) / 60000));
  return fill(fmt, { h: Math.floor(mins / 60), m: mins % 60 });
}

export function bookingErrorKey(e: unknown): MessageKey {
  if (!(e instanceof ApiError)) return "genericError";
  return (({
    insufficient_points: "b_errPoints",
    discount_changed: "b_discountChanged",
    out_of_stock: "outOfStock",
    own_shop: "b_errOwn",
    shop_not_live: "b_errShop",
    booking_expired: "b_expired",
    booking_closed: "b_closed",
    request_expired: "d_expired",
    request_closed: "b_closed",
    customer_not_found: "rd_errCustomer",
    review_window_closed: "rv_errWindow",
    purchase_not_found: "genericError",
    subscription_required: "r_errPlan",
    offer_closed: "rw_closed",
  } as Record<string, MessageKey>)[e.code] ?? "genericError");
}
