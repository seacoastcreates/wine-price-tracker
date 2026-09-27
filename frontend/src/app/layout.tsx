import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cellar Index",
  description: "Price history and 12-week forecasts for popular wines",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              <span className="text-accent">●</span> Cellar Index
            </Link>
            <span className="text-sm text-ink-2">Wine price tracking and forecasting</span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
        <footer className="border-t border-line py-6 text-center text-xs text-muted">
          Next.js · FastAPI · PostgreSQL · scikit-learn on Amazon SageMaker
        </footer>
      </body>
    </html>
  );
}
