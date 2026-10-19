"use client";

import RetailerNav from "@/components/RetailerNav";
import { useI18n } from "@/lib/i18n";

/** "Could not load" with a retry button, instead of an endless "Loading…" (deep audit B4). */
export default function LoadError({ onRetry, nav }: { onRetry?: () => void; nav?: boolean }) {
  const { t } = useI18n();
  return (
    <main className="stack">
      {nav && <RetailerNav />}
      <div className="card error stack" role="alert">
        {t("loadError")}
        <button className="btn secondary" onClick={onRetry ?? (() => window.location.reload())}>{t("retry")}</button>
      </div>
    </main>
  );
}

/** Page placeholder: "Loading…", or the retry card once a load has failed. */
export function PageLoading({ failed, onRetry, nav }: { failed: boolean; onRetry?: () => void; nav?: boolean }) {
  const { t } = useI18n();
  if (failed) return <LoadError onRetry={onRetry} nav={nav} />;
  return <main className="stack">{nav && <RetailerNav />}<div className="card">{t("loading")}</div></main>;
}
