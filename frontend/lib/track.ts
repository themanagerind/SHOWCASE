// Shop analytics events (SPEC 4.9). Fire-and-forget: tracking never blocks or breaks the page.
import { API_URL } from "@/lib/api";

const ANON = "showcase.anon";

/** Random per-browser id; the backend uses the customer id instead when logged in. Nothing personal. */
function anonId(): string | null {
  try {
    let id = localStorage.getItem(ANON);
    if (!id) { id = crypto.randomUUID(); localStorage.setItem(ANON, id); }
    return id;
  } catch {
    return null;
  }
}

export function track(slug: string, eventType: "shop_view" | "product_view" | "whatsapp_click" | "call_click", productId?: string) {
  try {
    const token = localStorage.getItem("showcase.access");
    fetch(`${API_URL}/events`, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ slug, event_type: eventType, anon_id: anonId(), product_id: productId ?? null }),
    }).catch(() => {});
  } catch { /* ignore */ }
}
