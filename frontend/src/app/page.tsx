import Link from "next/link";
import { api, wineTitle, type ListParams } from "@/lib/api";
import { Chance, Delta, ShelfPrice, SourceNote, StatTile } from "@/components/ui";

const STYLES = ["red", "white", "rose", "sparkling", "dessert"];
const TIERS = ["everyday", "premium", "luxury"];
const VIEWS = {
  featured: { label: "Popular wines", params: { featured: true, sort: "name" } },
  rising: { label: "Most likely to rise", params: { sort: "likely_up" } },
  investor: { label: "Collector watch", params: { investor: true, sort: "likely_up" } },
  all: { label: "All wines", params: { sort: "name" } },
} as const;
const PAGE = 50;

type State = { view: keyof typeof VIEWS; style?: string; tier?: string; q?: string; page: number };

function href(s: State, patch: Partial<State>) {
  const next = { ...s, page: 0, ...patch };
  const qs = new URLSearchParams();
  if (next.view !== "featured") qs.set("view", next.view);
  if (next.style) qs.set("style", next.style);
  if (next.tier) qs.set("tier", next.tier);
  if (next.q) qs.set("q", next.q);
  if (next.page) qs.set("page", String(next.page));
  return qs.size ? `/?${qs}` : "/";
}

function Chip({ label, to, active, pill = true }: { label: string; to: string; active: boolean; pill?: boolean }) {
  return (
    <Link
      href={to}
      className={`${pill ? "rounded-full px-3 py-1" : "rounded-md px-3 py-1.5"} border text-sm ${
        active ? "border-ink bg-ink text-page" : "border-line bg-surface text-ink-2 hover:text-ink"
      }`}
    >
      {label}
    </Link>
  );
}

export default async function Home({ searchParams }: PageProps<"/">) {
  const sp = await searchParams;
  const str = (k: string) => (typeof sp[k] === "string" && sp[k] ? (sp[k] as string) : undefined);
  const q = str("q");
  const rawView = str("view");
  const s: State = {
    view: q ? "all" : rawView && rawView in VIEWS ? (rawView as State["view"]) : "featured",
    style: str("style"),
    tier: str("tier"),
    q,
    page: Number(str("page") ?? 0) || 0,
  };
  const params: ListParams = { ...VIEWS[s.view].params, style: s.style, tier: s.tier, q: s.q, offset: s.page * PAGE };
  const [list, model] = await Promise.all([api.wines(params), api.model()]);
  const up1 = model?.metrics.price_change?.["1"]?.up;
  const up4 = model?.metrics.price_change?.[String(model?.horizon)]?.up;

  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">Wine prices, tracked and forecast</h1>
      <p className="mt-2 mb-6 max-w-3xl text-ink-2">
        Ten years of official shelf prices for {model?.metrics.series?.toLocaleString() ?? "thousands of"} wines, and a
        model that estimates each bottle&apos;s chance of a price rise or cut over the next year.
      </p>

      <SourceNote />

      {model && up1 && up4 && (
        <section className="mb-8 grid gap-3 sm:grid-cols-3">
          <StatTile
            label="List prices that change in a quarter"
            value={`${model.metrics.share_price_changed_pct}%`}
            sub="Prices are sticky, so the question is which ones will move"
          />
          <StatTile
            label="Ranking skill for price rises (ROC AUC)"
            value={`${up1.roc_auc} next quarter`}
            sub={`${up4.roc_auc} over a year · 0.5 = random guessing`}
          />
          <StatTile
            label="Model"
            value={<span className="text-base">{model.model_version}</span>}
            sub={`Trained on data through ${model.metrics.data_through}`}
          />
        </section>
      )}

      <div className="mb-4 flex flex-wrap gap-2" role="tablist">
        {(Object.keys(VIEWS) as State["view"][]).map((v) => (
          <Chip key={v} label={VIEWS[v].label} to={href(s, { view: v, q: undefined })} active={s.view === v} pill={false} />
        ))}
      </div>

      {s.view === "investor" && (
        <p className="mb-4 max-w-3xl text-sm text-ink-2">
          Vintage-dated premium and luxury wines, ranked by the model&apos;s chance of a list-price rise within a year.
          These are retail shelf prices at a state retailer, not auction or secondary-market prices, so treat them as
          a signal of retail pricing momentum rather than investment returns.
        </p>
      )}

      <div className="mb-4 flex flex-col gap-3">
        <form className="flex gap-2" action="/">
          <input type="hidden" name="view" value="all" />
          {s.style && <input type="hidden" name="style" value={s.style} />}
          {s.tier && <input type="hidden" name="tier" value={s.tier} />}
          <input
            name="q"
            defaultValue={s.q}
            placeholder="Search 8,000+ wines currently listed"
            className="w-full max-w-sm rounded-md border border-line bg-surface px-3 py-2 text-sm"
          />
          <button className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-page">Search</button>
        </form>
        <div className="flex flex-wrap gap-2">
          <Chip label="All styles" to={href(s, { style: undefined })} active={!s.style} />
          {STYLES.map((st) => (
            <Chip key={st} label={st === "rose" ? "Rosé" : st[0].toUpperCase() + st.slice(1)} to={href(s, { style: st })} active={s.style === st} />
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Chip label="All prices" to={href(s, { tier: undefined })} active={!s.tier} />
          {TIERS.map((t) => (
            <Chip key={t} label={t === "everyday" ? "Under $25" : t === "premium" ? "$25–75" : "$75+"} to={href(s, { tier: t })} active={s.tier === t} />
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="border-b border-line text-left text-ink-2">
            <tr>
              <th className="px-4 py-3 font-medium">Wine</th>
              <th className="px-4 py-3 text-right font-medium">Shelf price</th>
              <th className="px-4 py-3 text-right font-medium">1 yr</th>
              <th className="px-4 py-3 text-right font-medium">5 yr</th>
              <th className="px-4 py-3 font-medium">Chance of a rise within a year</th>
            </tr>
          </thead>
          <tbody>
            {list?.items.map((w) => (
              <tr key={w.slug} className="border-b border-line last:border-0 hover:bg-page">
                <td className="px-4 py-3">
                  <Link href={`/wines/${w.slug}`} className="font-medium hover:underline">
                    {wineTitle(w)}
                  </Link>
                  <div className="text-xs text-muted">
                    <span className="capitalize">{w.style === "rose" ? "rosé" : w.style}</span>
                    {w.region ? ` · ${w.region}` : ""} · {w.size.replace(" ML", " ml")}
                    {w.vintage === "NV" ? " · non-vintage or vintage not listed" : ""}
                  </div>
                </td>
                <td className="px-4 py-3 text-right font-medium"><ShelfPrice wine={w} /></td>
                <td className="px-4 py-3 text-right"><Delta pct={w.change_1y_pct} /></td>
                <td className="px-4 py-3 text-right"><Delta pct={w.change_5y_pct} /></td>
                <td className="px-4 py-3">
                  <Chance p={w.p_up_1y} tone="up" />
                  {w.p_up_1y != null && w.up_pct != null && w.p_up_1y >= 0.05 && (
                    <span className="ml-2 text-xs text-muted">typically +{Math.round(w.up_pct)}%</span>
                  )}
                </td>
              </tr>
            ))}
            {list?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-ink-2">No wines match these filters.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {list && list.total > PAGE && (
        <div className="mt-4 flex items-center justify-between text-sm text-ink-2">
          <span>
            {(s.page * PAGE + 1).toLocaleString()}–{Math.min((s.page + 1) * PAGE, list.total).toLocaleString()} of{" "}
            {list.total.toLocaleString()}
          </span>
          <span className="flex gap-2">
            {s.page > 0 && <Chip label="← Previous" to={href(s, { page: s.page - 1 })} active={false} pill={false} />}
            {(s.page + 1) * PAGE < list.total && <Chip label="Next →" to={href(s, { page: s.page + 1 })} active={false} pill={false} />}
          </span>
        </div>
      )}
    </>
  );
}
