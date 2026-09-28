import { usd, type WineSummary } from "@/lib/api";

export function Delta({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-muted">—</span>;
  const cls = pct > 0 ? "text-up" : pct < 0 ? "text-down" : "text-ink-2";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "";
  return (
    <span className={`tabular ${cls}`}>
      {arrow} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

export function SourceNote() {
  return (
    <aside className="mb-8 rounded-r-lg border-l-4 border-gold bg-surface-2 px-4 py-3 text-sm text-ink-2">
      <strong className="text-ink">Real prices:</strong> every price comes from the{" "}
      <a
        className="underline hover:text-ink"
        href="https://www.pa.gov/en/agencies/lcb/about-us/reports-and-publications/quarterly-price-listing.html"
      >
        Pennsylvania Liquor Control Board&apos;s quarterly price lists
      </a>
      , the state-run retailer&apos;s official shelf prices, October 2016 to today. List prices exclude sales tax.
    </aside>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="card p-5">
      <div className="font-semibold">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-1 text-sm text-ink-2">{sub}</div>}
    </div>
  );
}

export function ShelfPrice({ wine }: { wine: Pick<WineSummary, "regular_price" | "promo_price" | "promo_type"> }) {
  if (wine.promo_price == null) return <span className="tabular">{usd(wine.regular_price)}</span>;
  return (
    <span className="tabular">
      {usd(wine.promo_price)}{" "}
      <span className="text-xs text-muted line-through">{usd(wine.regular_price)}</span>{" "}
      <span className="badge">{wine.promo_type === "clearance" ? "Clearance" : "Sale"}</span>
    </span>
  );
}

/** A small horizontal meter: probability as a filled bar plus the number. */
export function Chance({ p, tone }: { p: number | null; tone: "up" | "down" }) {
  if (p == null) return <span className="text-muted">—</span>;
  const pctVal = Math.round(p * 100);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative inline-block h-1.5 w-14 overflow-hidden rounded-full bg-grid">
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${Math.max(pctVal, 2)}%`, background: tone === "up" ? "var(--up)" : "var(--down)" }}
        />
      </span>
      <span className="tabular w-9 text-right">{pctVal < 1 ? "<1%" : `${pctVal}%`}</span>
    </span>
  );
}

/** Shelf price vs fair price: a deal or a premium only when outside the fair range. */
export function FairValue({ wine }: { wine: Pick<WineSummary, "regular_price" | "fair_low" | "fair_high" | "value_pct"> }) {
  if (wine.value_pct == null || wine.regular_price == null || wine.fair_low == null || wine.fair_high == null)
    return <span className="text-muted">—</span>;
  const pctAbs = Math.abs(Math.round(wine.value_pct));
  if (wine.regular_price < wine.fair_low) return <span className="tabular whitespace-nowrap text-up">{pctAbs}% below</span>;
  if (wine.regular_price > wine.fair_high) return <span className="tabular whitespace-nowrap text-ink-2">{pctAbs}% premium</span>;
  return <span className="whitespace-nowrap text-ink-2">Fairly priced</span>;
}
