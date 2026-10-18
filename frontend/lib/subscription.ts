export type Price = { base_paise: number; amount_paise: number; gst_paise: number; source: string };
export type PlanOption = { code: string; name: string; features: Record<string, unknown>; monthly: Price; yearly: Price };
export type Payment = {
  id: string; plan_code: string; billing_cycle: "MONTHLY" | "YEARLY"; amount_paise: number; gst_paise: number;
  status: string; gateway: string; reference: string | null; period_start: string | null; period_end: string | null;
  paid_at: string | null;
};
export type MySubscription = {
  status: "TRIAL" | "ACTIVE" | "GRACE" | "EXPIRED" | "CANCELLED" | null;
  plan_code: string | null;
  billing_cycle: "MONTHLY" | "YEARLY" | null;
  trial_ends_at: string | null;
  current_period_end: string | null;
  grace_ends_at: string | null;
  next_period: Payment | null;
  online_payment_available: boolean;
  payments: Payment[];
};
export type Checkout = { payment_id: string; gateway: string; key_id: string; order_id: string; amount_paise: number; currency: string };

type RazorpayResponse = { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string };
type RazorpayCtor = new (opts: Record<string, unknown>) => { open: () => void; on: (e: string, cb: () => void) => void };

/** Loads Razorpay Checkout on demand (only when the retailer actually pays). */
export function loadRazorpay(): Promise<RazorpayCtor> {
  const w = window as unknown as { Razorpay?: RazorpayCtor };
  if (w.Razorpay) return Promise.resolve(w.Razorpay);
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => (w.Razorpay ? resolve(w.Razorpay) : reject(new Error("Razorpay unavailable")));
    s.onerror = () => reject(new Error("Razorpay unavailable"));
    document.body.appendChild(s);
  });
}

export function openRazorpay(R: RazorpayCtor, co: Checkout, shopName: string): Promise<RazorpayResponse> {
  return new Promise((resolve, reject) => {
    const rz = new R({
      key: co.key_id, order_id: co.order_id, amount: co.amount_paise, currency: co.currency,
      name: "Showcase", description: shopName, theme: { color: "#0b2545" },
      handler: (resp: RazorpayResponse) => resolve(resp),
      modal: { ondismiss: () => reject(new Error("dismissed")) },
    });
    rz.on("payment.failed", () => reject(new Error("failed")));
    rz.open();
  });
}
