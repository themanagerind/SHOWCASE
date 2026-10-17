"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError, isLoggedIn, type Profile } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// Flow: login (if needed) → profile (if incomplete) → join → favourites.
function Join() {
  const { slug } = useParams<{ slug: string }>();
  const source = useSearchParams().get("src") === "qr" ? "QR" : "LINK";
  const router = useRouter();
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const self = `/${slug}/join?src=${source.toLowerCase()}`;
    if (!isLoggedIn()) {
      router.replace(`/login?next=${encodeURIComponent(self)}`);
      return;
    }
    (async () => {
      try {
        const me = await api<Profile>("/customers/me");
        if (!me.profile_complete) {
          router.replace(`/profile?next=${encodeURIComponent(self)}`);
          return;
        }
        await api(`/retailers/${slug}/join`, { method: "POST", body: JSON.stringify({ source }) });
        router.replace(`/favourites?joined=${encodeURIComponent(slug)}`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) router.replace(`/login?next=${encodeURIComponent(self)}`);
        else setError(e instanceof ApiError && e.status === 404 ? t("shopNotFound") : (e as Error).message);
      }
    })();
  }, [slug, source, router, t]);

  return <main><div className="card">{error ? <span className="error">{error}</span> : t("loading")}</div></main>;
}

export default function JoinPage() {
  return <Suspense><Join /></Suspense>;
}
