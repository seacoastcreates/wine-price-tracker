import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import Link from "next/link";
import Logo from "@/components/Logo";
import NavLinks from "@/components/NavLinks";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces", display: "swap", axes: ["opsz"] });

export const metadata: Metadata = {
  title: { default: "Cellar Index", template: "%s · Cellar Index" },
  description: "Ten years of official wine shelf prices, with forecasts, fair prices and vintage outlooks",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <div className="h-1 bg-accent" />
        <header className="sticky top-0 z-10 border-b border-line bg-surface/90 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <Logo />
              <span className="display text-xl font-semibold">Cellar Index</span>
            </Link>
            <NavLinks />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">{children}</main>
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-muted sm:flex-row sm:justify-between">
            <span>
              Prices: Pennsylvania Liquor Control Board quarterly price lists. Weather: NASA POWER. Supply: USDA
              California grape crush reports.
            </span>
            <span>
              Next.js · FastAPI model service · PostgreSQL · scikit-learn ·{" "}
              <a className="underline hover:text-ink" href="https://github.com/seacoastcreates/wine-price-tracker">
                Source on GitHub
              </a>
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
