// Thin client for the Showcase API. Tokens live in localStorage (MVP); refresh is automatic on 401.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

const ACCESS = "showcase.access";
const REFRESH = "showcase.refresh";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function saveTokens(access: string, refresh: string) {
  try {
    localStorage.setItem(ACCESS, access);
    localStorage.setItem(REFRESH, refresh);
  } catch {}
}

export function clearTokens() {
  try {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  } catch {}
}

export const isLoggedIn = () => !!read(ACCESS);

const SESSION_GONE = new Set(["session_ended", "session_expired", "token_reused", "account_disabled"]);

/** The server said this login no longer exists (logged out elsewhere, admin 12h limit, ...): go to login. */
function sessionGone() {
  clearTokens();
  if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
    location.href = `/login?reason=logged_out&next=${encodeURIComponent(location.pathname + location.search)}`;
  }
}

/** Ends this device's session on the server too, then forgets the tokens here. */
export async function logout(): Promise<void> {
  const refresh = read(REFRESH);
  try {
    if (refresh) {
      await fetch(`${API_URL}/auth/logout`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }),
      });
    }
  } finally {
    clearTokens();
    try { sessionStorage.clear(); } catch { /* ignore */ }
    try { if ("caches" in window) for (const k of await caches.keys()) await caches.delete(k); } catch { /* ignore */ }
  }
}

let refreshing: Promise<boolean> | null = null;

/**
 * One refresh at a time (deep audit): the header and the page used to send two refreshes with the same token;
 * the server reads the second as a stolen token and logs the user out. All callers in this tab share one
 * request, and a Web Lock makes other tabs wait too — if another tab already rotated the token, we just use it.
 */
function refreshTokens(): Promise<boolean> {
  if (!refreshing) refreshing = refreshOnce().finally(() => { refreshing = null; });
  return refreshing;
}

async function refreshOnce(): Promise<boolean> {
  const before = read(REFRESH);
  if (!before) return false;
  const run = async (): Promise<boolean> => {
    const current = read(REFRESH);
    if (!current) return false;
    if (current !== before) return true; // another tab refreshed while we waited for the lock
    const r = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current }),
    });
    if (!r.ok) {
      sessionGone();
      return false;
    }
    const data = await r.json();
    saveTokens(data.access_token, data.refresh_token);
    return true;
  };
  const locks = typeof navigator !== "undefined" ? (navigator as Navigator & { locks?: LockManager }).locks : undefined;
  return locks ? locks.request("showcase-refresh", run) : run();
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = read(ACCESS);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (r.status === 401 && retry && (await refreshTokens())) return api<T>(path, init, false);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    if (r.status === 401 && SESSION_GONE.has(body.error)) sessionGone();
    throw new ApiError(r.status, body.error ?? "error", body.message ?? r.statusText);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export type Product = {
  id: string;
  name: string;
  description: string | null;
  price_paise: number;
  mrp_paise: number | null;
  wallet_discount_paise: number;
  stock_qty: number;
  photos: string[];
};

export type Shop = {
  slug: string;
  shop_name: string;
  category: string;
  description: string | null;
  photos: string[];
  address_line: string;
  city: string;
  pincode: string;
  timings: Record<string, string[][]>;
  phone: string | null;
  whatsapp_url: string | null;
  rating_avg: number;
  rating_count: number;
};

export type Storefront = { shop: Shop; products: Product[] };

export type Profile = {
  phone: string;
  name: string | null;
  preferred_language: string;
  pincode: string | null;
  city: string | null;
  contact_consent: boolean;
  search_radius_km: number;
  profile_complete: boolean;
};

export const RADIUS_OPTIONS = [2, 5, 10, 25, 50] as const;

export type DiscoveredShop = {
  slug: string;
  shop_name: string;
  category: string;
  city: string;
  photo: string | null;
  rating_avg: number;
  rating_count: number;
  distance_m: number | null;
  whatsapp_url: string | null;
  is_favourite: boolean;
};

export type FoundProduct = {
  id: string;
  name: string;
  photo: string | null;
  price_paise: number;
  mrp_paise: number | null;
  wallet_discount_paise: number;
  in_stock: boolean;
  shop_slug: string;
  shop_name: string;
  shop_city: string;
  distance_m: number | null;
};

export type ProductSearch = { radius_km: number; used_location: boolean; items: FoundProduct[] };

export type Discovery = { radius_km: number; used_location: boolean; items: DiscoveredShop[] };

/** units: the translated "m" and "km" (t("u_m"), t("km")). */
export const distanceLabel = (m: number, units = { m: "m", km: "km" }) =>
  m < 50 ? `< 50 ${units.m}` : m < 1000 ? `${Math.round(m / 10) * 10} ${units.m}` : `${(m / 1000).toFixed(1)} ${units.km}`;

export type Favourite = {
  slug: string;
  shop_name: string;
  category: string;
  city: string;
  photo: string | null;
  whatsapp_url: string | null;
  source: "LINK" | "QR" | "DISCOVERY";
  available: boolean; // false: the shop's plan has expired (SPEC 5)
  limited_view: boolean; // expired, but I have an open booking there
};

/** ₹199 for whole rupees, ₹199.50 otherwise (never ₹199.5). */
export const rupees = (paise: number) =>
  `₹${(paise / 100).toLocaleString("en-IN", paise % 100 === 0 ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
