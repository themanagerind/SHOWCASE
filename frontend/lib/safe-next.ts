/**
 * Only same-site paths are allowed as a post-login/profile destination (no open redirect).
 * "/\evil.com", "//evil.com", "https://evil.com" and control characters all fall back to `fallback`.
 */
export function safeNext(next: string | null | undefined, fallback = "/favourites"): string {
  if (!next || !next.startsWith("/") || /[\\\u0000-\u001f]/.test(next)) return fallback;
  try {
    const base = typeof window === "undefined" ? "https://showcase.invalid" : window.location.origin;
    const u = new URL(next, base);
    return u.origin === base ? u.pathname + u.search + u.hash : fallback;
  } catch {
    return fallback;
  }
}
