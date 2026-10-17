import type { Metadata, Viewport } from "next";
import Header from "@/components/Header";
import SwRegister from "@/components/SwRegister";
import { I18nProvider } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "Showcase",
  description: "Your favourite local shops, online",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f6e5c" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="hi">
      <body>
        <I18nProvider>
          <Header />
          {children}
          <SwRegister />
        </I18nProvider>
      </body>
    </html>
  );
}
