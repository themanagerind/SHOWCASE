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

async function refreshTokens(): Promise<boolean> {
  const refresh = read(REFRESH);
  if (!refresh) return false;
  const r = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!r.ok) {
    clearTokens();
    return false;
  }
  const data = await r.json();
  saveTokens(data.access_token, data.refresh_token);
  return true;
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
  profile_complete: boolean;
};

export type Favourite = {
  slug: string;
  shop_name: string;
  category: string;
  city: string;
  photo: string | null;
  whatsapp_url: string | null;
  source: "LINK" | "QR" | "DISCOVERY";
};

export const rupees = (paise: number) =>
  `₹${(paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
