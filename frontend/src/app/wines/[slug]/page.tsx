import Link from "next/link";
import { notFound } from "next/navigation";
import { api, pct, quarterLabel, usd, wineTitle } from "@/lib/api";
import { Chance, Delta, ShelfPrice, SourceNote, StatTile } from "@/components/ui";
import PriceChart from "@/components/PriceChart";
import WhatIf from "@/components/WhatIf";

export default async function WinePage({ params }: PageProps<"/wines/[slug]">) {
  const { slug } = await params;
  const [wine, prices, forecast, vintages, insights] = await Promise.all([
    api.wine(slug),
    api.prices(slug),
    api.forecast(slug),
    api.vintages(slug),
    api.insights(slug),
  ]);
  if (!wine || !prices) notFound();

  const points = forecast?.points ?? [];
  const dw = insights?.drinking_window;
  const nv = insights?.next_vintage;
  const yearOut = points.at(-1);
  const changes = prices.filter((p, i) => i > 0 && p.regular_price !== prices[i - 1].regular_price).length;
  const sales = prices.filter((p) => p.promo_type === "sale").length;

  return (
    <>
      <Link href="/" className="text-sm text-ink-2 hover:text-accent">← All wines</Link>
      <h1 className="display mt-3 text-4xl font-semibold">{wineTitle(wine)}</h1>
      <p className="mt-1 mb-6 text-ink-2">
        <span className="capitalize">{wine.style === "rose" ? "rosé" : wine.style}</span>
        {wine.region ? ` · ${wine.region}` : ""} · {wine.size.replace(" ML", " ml")}
        {wine.vintage === "NV" ? " · non-vintage or vintage not listed" : ` · ${wine.vintage} vintage`}
        {wine.first_date ? ` · tracked since ${quarterLabel(wine.first_date)}` : ""}
        {!wine.is_active ? " · no longer listed" : ""}
      </p>

      <section className="mb-6 grid gap-3 sm:grid-cols-3">
        <StatTile
          label={`Shelf price, ${wine.latest_date ? quarterLabel(wine.latest_date) : ""}`}
          value={<ShelfPrice wine={wine} />}
          sub={
            <>
              {prices.length} quarters on record · {changes} list-price change{changes === 1 ? "" : "s"} · on sale in {sales}
            </>
          }
        />
        <StatTile
          label="List-price change, past year"
          value={<Delta pct={wine.change_1y_pct} />}
          sub={<>Past 5 years: <Delta pct={wine.change_5y_pct} /></>}
        />
        <StatTile
          label="Outlook for the next 12 months"
          value={yearOut ? <span className="text-xl">{pct(yearOut.p_up)} chance of a rise</span> : "—"}
          sub={
            yearOut ? (
              <>
                typically +{Math.round(yearOut.up_pct)}% · {pct(yearOut.p_down)} chance of a cut (typically{" "}
                {Math.round(yearOut.down_pct)}%)
              </>
            ) : (
              "No forecast: wine is no longer listed"
            )
          }
        />
      </section>

      <PriceChart prices={prices} forecast={points} />

      {points.length > 0 && (
        <section className="mt-6 card p-4">
          <h2 className="mb-3 font-semibold">Chance the list price will differ from today&apos;s {usd(wine.regular_price)}</h2>
          <div className="grid gap-2 text-sm sm:grid-cols-[8rem_1fr_1fr]">
            <div className="text-ink-2">By</div>
            <div className="text-ink-2">Higher</div>
            <div className="text-ink-2">Lower</div>
            {points.map((p) => (
              <div key={p.date} className="contents">
                <div className="tabular">{quarterLabel(p.date)}</div>
                <div><Chance p={p.p_up} tone="up" /></div>
                <div><Chance p={p.p_down} tone="down" /></div>
              </div>
            ))}
          </div>
        </section>
      )}

      {(dw || nv || wine.fair_price != null) && (
        <section className="mt-6 grid gap-3 sm:grid-cols-3">
          {wine.fair_price != null && (
            <StatTile
              label="Fair price"
              value={usd(wine.fair_price)}
              sub={
                <>
                  Comparable wines cost {usd(wine.fair_low)}–{usd(wine.fair_high)} (80% range).{" "}
                  {wine.regular_price == null || wine.fair_low == null || wine.fair_high == null
                    ? null
                    : wine.regular_price < wine.fair_low
                      ? `At ${usd(wine.regular_price)} it is priced ${Math.abs(Math.round(wine.value_pct ?? 0))}% below them.`
                      : wine.regular_price > wine.fair_high
                        ? `At ${usd(wine.regular_price)} it carries a ${Math.round(wine.value_pct ?? 0)}% premium: often reputation or scarcity the model can't see.`
                        : `At ${usd(wine.regular_price)} it is fairly priced for what it is.`}
                </>
              }
            />
          )}
          {dw && (
            <StatTile
              label="Typical drinking window"
              value={`${dw.opens}–${dw.closes}`}
              sub={
                <>
                  {dw.status === "before"
                    ? `Opens in ${dw.opens - new Date().getFullYear()} year(s)`
                    : dw.status === "in"
                      ? "In its window now"
                      : "Past its typical window"}
                  {" · "}rule of thumb, {dw.basis}
                </>
              }
            />
          )}
          {nv && (
            <StatTile
              label={`Next vintage (${nv.next_vintage}) vs this one`}
              value={`${pct(nv.p_up)} chance priced higher`}
              sub={
                <>
                  Typical change {nv.p50_pct > 0 ? "+" : ""}
                  {nv.p50_pct}% (80% range {nv.p10_pct}% to{" "}
                  {nv.p90_pct}%) · {pct(nv.p_down)} chance priced lower
                </>
              }
            />
          )}
        </section>
      )}

      {wine.is_active && wine.regular_price != null && points.length > 0 && (
        <WhatIf slug={wine.slug} listPrice={wine.regular_price} promoType={wine.promo_type} />
      )}

      {vintages && vintages.length > 1 && (
        <section className="mt-6 overflow-x-auto card">
          <h2 className="px-4 pt-4 font-semibold">Other vintages</h2>
          <p className="px-4 pb-3 text-sm text-ink-2">Each vintage is tracked as its own wine.</p>
          <table className="w-full min-w-[640px] text-sm">
            <thead className="table-head border-y border-line text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Vintage</th>
                <th className="px-4 py-2 font-medium">Last listed</th>
                <th className="px-4 py-2 text-right font-medium">Shelf price</th>
                <th className="px-4 py-2 text-right font-medium">1yr History</th>
                <th className="px-4 py-2 font-medium">Chance of a rise within a year</th>
              </tr>
            </thead>
            <tbody>
              {vintages.map((v) => (
                <tr key={v.slug} className={`border-b border-line last:border-0 ${v.slug === wine.slug ? "bg-surface-2" : ""}`}>
                  <td className="px-4 py-2">
                    {v.slug === wine.slug ? (
                      <span className="font-medium">{v.vintage === "NV" ? "No vintage listed" : v.vintage} (this page)</span>
                    ) : (
                      <Link href={`/wines/${v.slug}`} className="font-medium hover:underline">
                        {v.vintage === "NV" ? "No vintage listed" : v.vintage}
                      </Link>
                    )}
                  </td>
                  <td className="px-4 py-2 text-ink-2">
                    {v.is_active ? "Listed now" : v.latest_date ? quarterLabel(v.latest_date) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right"><ShelfPrice wine={v} /></td>
                  <td className="px-4 py-2 text-right"><Delta pct={v.change_1y_pct} /></td>
                  <td className="px-4 py-2">{v.is_active ? <Chance p={v.p_up_1y} tone="up" /> : <span className="text-muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="mt-6">
        <SourceNote />
      </div>
      {forecast && (
        <p className="text-xs text-muted">
          Model {forecast.model_version}: {forecast.algorithm}.
        </p>
      )}
    </>
  );
}
