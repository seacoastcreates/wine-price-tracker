import Link from "next/link";
import { api, wineTitle, type ListParams } from "@/lib/api";
import { Chance, Delta, FairValue, ShelfPrice, SourceNote, StatTile } from "@/components/ui";

const STYLES = ["red", "white", "rose", "sparkling", "dessert"];
const TIERS = ["everyday", "premium", "luxury"];
const VIEWS = {
  featured: { label: "Popular wines", params: { featured: true, sort: "name" } },
  rising: { label: "Most likely to rise", params: { sort: "likely_up" } },
  investor: { label: "Collector watch", params: { investor: true, sort: "likely_up" } },
  value: { label: "Best values", params: { sort: "value" } },
  all: { label: "All wines", params: { sort: "name" } },
} as const;
const PAGE = 50;

type Dir = "asc" | "desc";
type State = {
  view: keyof typeof VIEWS;
  style?: string;
  tier?: string;
  q?: string;
  sort?: string;
  dir?: Dir;
  page: number;
};

// Sortable columns. Text sorts A→Z on the first click; numbers sort high→low first.
const COLUMNS: { key: string; label: string; first: Dir; align: "left" | "right" }[] = [
  { key: "name", label: "Wine", first: "asc", align: "left" },
  { key: "price", label: "Shelf price", first: "desc", align: "right" },
  { key: "change_1y", label: "1yr History", first: "desc", align: "right" },
  { key: "change_5y", label: "5yr History", first: "desc", align: "right" },
  { key: "fair", label: "vs fair price", first: "desc", align: "right" },
  { key: "likely_up", label: "Chance of a rise within a year", first: "desc", align: "left" },
];

function href(s: State, patch: Partial<State>) {
  const next = { ...s, page: 0, ...patch };
  const qs = new URLSearchParams();
  if (next.view !== "featured") qs.set("view", next.view);
  if (next.style) qs.set("style", next.style);
  if (next.tier) qs.set("tier", next.tier);
  if (next.q) qs.set("q", next.q);
  if (next.sort) qs.set("sort", next.sort);
  if (next.sort && next.dir) qs.set("dir", next.dir);
  if (next.page) qs.set("page", String(next.page));
  return qs.size ? `/?${qs}` : "/";
}

function SortHeader({ col, s, active, dir }: { col: (typeof COLUMNS)[number]; s: State; active: boolean; dir: Dir }) {
  const next: Dir = active ? (dir === "asc" ? "desc" : "asc") : col.first;
  const arrow = active ? (dir === "asc" ? "▲" : "▼") : "↕";
  return (
    <th
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      className={`px-4 py-3 font-medium ${col.align === "right" ? "text-right" : ""}`}
    >
      <Link
        href={href(s, { sort: col.key, dir: next })}
        className={`hover:text-ink ${active ? "text-ink" : ""} ${col.key === "likely_up" ? "" : "whitespace-nowrap"}`}
        title={`Sort ${next === "asc" ? (col.key === "name" ? "A to Z" : "low to high") : col.key === "name" ? "Z to A" : "high to low"}`}
      >
        {col.label}
        <span aria-hidden className={`ml-1 text-xs ${active ? "" : "text-muted"}`}>{arrow}</span>
      </Link>
    </th>
  );
}

function Chip({ label, to, active, pill = true }: { label: string; to: string; active: boolean; pill?: boolean }) {
  const cls = pill ? `chip ${active ? "chip-active" : ""}` : `segment ${active ? "segment-active" : ""}`;
  return (
    <Link href={to} className={cls}>
      {label}
    </Link>
  );
}

function Tab({ label, to, active }: { label: string; to: string; active: boolean }) {
  return (
    <Link href={to} role="tab" aria-selected={active} className={`tab ${active ? "tab-active" : ""}`}>
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
    sort: COLUMNS.some((c) => c.key === str("sort")) ? str("sort") : undefined,
    dir: str("dir") === "asc" || str("dir") === "desc" ? (str("dir") as Dir) : undefined,
    page: Number(str("page") ?? 0) || 0,
  };
  const activeSort = s.sort ?? VIEWS[s.view].params.sort;
  const activeDir: Dir = s.dir ?? COLUMNS.find((c) => c.key === activeSort)?.first ?? "asc";
  const params: ListParams = {
    ...VIEWS[s.view].params,
    ...(s.sort ? { sort: s.sort, dir: activeDir } : {}),
    style: s.style,
    tier: s.tier,
    q: s.q,
    offset: s.page * PAGE,
  };
  const [list, model] = await Promise.all([api.wines(params), api.model()]);
  const up1 = model?.metrics.price_change?.["1"]?.up;
  const up4 = model?.metrics.price_change?.[String(model?.horizon)]?.up;

  return (
    <>
      <div className="eyebrow">Pennsylvania state store prices · 2016 to today</div>
      <h1 className="display mt-2 text-4xl font-semibold sm:text-5xl">Wine prices, tracked and forecast</h1>
      <p className="mt-3 mb-8 max-w-3xl text-lg text-ink-2">
        Ten years of official shelf prices for {model?.metrics.series?.toLocaleString() ?? "thousands of"} wines, and a
        model that estimates each bottle&apos;s chance of a price rise or cut over the next year.
      </p>

      <SourceNote />

      {model && up1 && up4 && (
        <section className="mb-8 grid gap-3 sm:grid-cols-3">
          <StatTile
            label="How often list prices change"
            value={`${model.metrics.share_price_changed_pct}%`}
            sub="of wines get a new list price in a typical quarter, so the real question is which ones will move"
          />
          <StatTile
            label="How well the model spots upcoming price rises"
            value={`${up1.roc_auc} next quarter`}
            sub={`${up4.roc_auc} over a year. This is ranking accuracy, the area under the receiver operating characteristic curve (ROC AUC): 1.0 is perfect, 0.5 is a coin flip.`}
          />
          <StatTile
            label="Model"
            value={<span className="text-base">{model.model_version}</span>}
            sub={`Trained on data through ${model.metrics.data_through}`}
          />
        </section>
      )}

      <div className="mb-5 flex gap-6 overflow-x-auto border-b border-line" role="tablist">
        {(Object.keys(VIEWS) as State["view"][]).map((v) => (
          <Tab
            key={v}
            label={VIEWS[v].label}
            to={href(s, { view: v, q: undefined, sort: undefined, dir: undefined })}
            active={s.view === v}
          />
        ))}
      </div>

      {s.view === "value" && (
        <p className="mb-4 max-w-3xl text-sm text-ink-2">
          Wines whose shelf price is furthest below their fair price: what comparable wines cost, estimated from the
          region, grape, classification, age, bottle size, name and the producer&apos;s other wines, by a model that never
          saw the wine&apos;s own price. The biggest gaps are often a famous producer&apos;s second or entry-level wines:
          the model knows the producer&apos;s overall price level but can&apos;t always tell where a wine sits within
          its range.
        </p>
      )}

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
            className="field w-full max-w-sm"
          />
          <button className="btn-primary">Search</button>
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

      <div className="overflow-x-auto card">
        <table className="w-full min-w-[880px] text-sm">
          <thead className="table-head border-b border-line text-left">
            <tr>
              {COLUMNS.map((c) => (
                <SortHeader key={c.key} col={c} s={s} active={activeSort === c.key} dir={activeDir} />
              ))}
            </tr>
          </thead>
          <tbody>
            {list?.items.map((w) => (
              <tr key={w.slug} className="border-b border-line last:border-0 hover:bg-surface-2">
                <td className="px-4 py-3">
                  <Link href={`/wines/${w.slug}`} className="font-medium hover:text-accent">
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
                <td className="px-4 py-3 text-right"><FairValue wine={w} /></td>
                <td className="px-4 py-3">
                  <Chance p={w.p_up_1y} tone="up" />
                  {w.p_up_1y != null && w.up_pct != null && w.p_up_1y >= 0.05 && (
                    <div className="mt-0.5 whitespace-nowrap text-xs text-muted">typically +{Math.round(w.up_pct)}% if it rises</div>
                  )}
                </td>
              </tr>
            ))}
            {list?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-ink-2">No wines match these filters.</td>
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
