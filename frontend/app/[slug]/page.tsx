import type { Metadata } from "next";
import ShopView from "./ShopView";
import type { Storefront } from "@/lib/api";

const SERVER_API = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001/api/v1";

async function load(slug: string): Promise<Storefront | null> {
  try {
    const r = await fetch(`${SERVER_API}/retailers/${encodeURIComponent(slug)}`, { next: { revalidate: 60 } });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

type Props = { params: Promise<{ slug: string }>; searchParams: Promise<{ src?: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const data = await load((await params).slug);
  return data ? { title: `${data.shop.shop_name} · Showcase`, description: data.shop.description ?? undefined } : {};
}

export default async function ShopPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const { src } = await searchParams;
  const data = await load(slug);
  return <ShopView data={data} slug={slug} source={src === "qr" ? "QR" : "LINK"} />;
}
