"use client";

import { fill } from "@/lib/bookings";
import { useI18n } from "@/lib/i18n";

/** Read-only stars, or a 1–5 picker when onChange is given. */
export default function Stars({ value, onChange, size = 20 }: { value: number; onChange?: (v: number) => void; size?: number }) {
  const { t } = useI18n();
  const label = (n: number | string) => fill(t("starsOf5"), { n });
  return (
    <span className={`stars ${onChange ? "pick" : ""}`} style={{ fontSize: size }} role={onChange ? "radiogroup" : "img"}
      aria-label={label(Number(value).toFixed(1).replace(/\.0$/, ""))}>
      {[1, 2, 3, 4, 5].map((n) => onChange ? (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={label(n)}
          className={n <= value ? "on" : ""} onClick={() => onChange(n)}>★</button>
      ) : (
        <span key={n} className={n <= Math.round(value) ? "on" : ""}>★</span>
      ))}
    </span>
  );
}
