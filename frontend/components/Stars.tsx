"use client";

/** Read-only stars, or a 1–5 picker when onChange is given. */
export default function Stars({ value, onChange, size = 20 }: { value: number; onChange?: (v: number) => void; size?: number }) {
  return (
    <span className={`stars ${onChange ? "pick" : ""}`} style={{ fontSize: size }} role={onChange ? "radiogroup" : "img"}
      aria-label={`${value} / 5`}>
      {[1, 2, 3, 4, 5].map((n) => onChange ? (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n}`}
          className={n <= value ? "on" : ""} onClick={() => onChange(n)}>★</button>
      ) : (
        <span key={n} className={n <= Math.round(value) ? "on" : ""}>★</span>
      ))}
    </span>
  );
}
