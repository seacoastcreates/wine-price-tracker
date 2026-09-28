import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import Link from "next/link";
import DunesLogo from "@/components/DunesLogo";
import Logo from "@/components/Logo";
import NavLinks from "@/components/NavLinks";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces", display: "swap", axes: ["opsz"] });

const FOOTER_LINKS = [
  ["/", "Wines"],
  ["/model", "How it works"],
  ["/architecture", "Architecture"],
] as const;

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
          <nav aria-label="Footer" className="mx-auto flex max-w-6xl flex-wrap gap-x-6 gap-y-2 px-4 pt-6 text-sm">
            {FOOTER_LINKS.map(([href, label]) => (
              <Link key={href} href={href} className="font-medium text-ink-2 hover:text-accent">
                {label}
              </Link>
            ))}
          </nav>
          <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-4 text-xs text-muted sm:flex-row sm:justify-between">
            <span>
              Prices: Pennsylvania Liquor Control Board quarterly price lists. Weather: NASA POWER. Supply: USDA
              California grape crush reports.
            </span>
            <span>
              Next.js · FastAPI model service · PostgreSQL · scikit-learn ·{" "}
              <a className="whitespace-nowrap underline hover:text-ink" href="https://github.com/seacoastcreates/wine-price-tracker">
                Source on GitHub
              </a>
            </span>
          </div>
          <div className="mx-auto max-w-6xl px-4 pb-6">
            <a
              href="https://36dunes.com"
              className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink"
            >
              Made by <DunesLogo size={18} /> <span className="font-semibold">36 Dunes</span>
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
