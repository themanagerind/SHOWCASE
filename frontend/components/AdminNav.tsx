"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/admin", label: "Retailers" },
  { href: "/admin/plans", label: "Plans & prices" },
  { href: "/admin/rewards", label: "Rewards" },
  { href: "/admin/settings", label: "Settings" },
  { href: "/admin/audit", label: "Audit log" },
];

export default function AdminNav() {
  const path = usePathname();
  return (
    <nav className="rnav">
      {TABS.map((t) => {
        const on = t.href === "/admin" ? path === "/admin" || path.startsWith("/admin/retailers") : path.startsWith(t.href);
        return <Link key={t.href} href={t.href} className={on ? "on" : ""}>{t.label}</Link>;
      })}
    </nav>
  );
}
