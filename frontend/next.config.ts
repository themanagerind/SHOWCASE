import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // THE-MANAGER prefill landing: never leak the one-time token through the Referer header (SPEC 4.12).
  async headers() {
    return [{ source: "/welcome/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] },
            { source: "/welcome", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] }];
  },
};

export default nextConfig;
