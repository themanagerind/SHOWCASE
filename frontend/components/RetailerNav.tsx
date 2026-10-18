"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/lib/i18n";

const TABS = [
  { href: "/retailer", key: "r_dashboard" },
  { href: "/retailer/plan", key: "r_plan_tab" },
  { href: "/retailer/products", key: "r_products" },
  { href: "/retailer/bookings", key: "rb_tab" },
  { href: "/retailer/reviews", key: "rv_tab" },
  { href: "/retailer/analytics", key: "an_tab" },
  { href: "/retailer/share", key: "r_share" },
  { href: "/retailer/customers", key: "r_customers" },
] as const;

export default function RetailerNav() {
  const { t } = useI18n();
  const path = usePathname();
  return (
    <nav className="rnav">
      {TABS.map((tab) => {
        const on = tab.href === "/retailer" ? path === "/retailer" : path.startsWith(tab.href);
        return (
          <Link key={tab.href} href={tab.href} className={on ? "on" : ""}>{t(tab.key)}</Link>
        );
      })}
    </nav>
  );
}
