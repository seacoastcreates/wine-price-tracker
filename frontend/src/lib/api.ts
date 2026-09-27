const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type WineSummary = {
  slug: string;
  name: string;
  size: string;
  style: string;
  tier: string;
  latest_vintage: string | null;
  is_featured: boolean;
  is_active: boolean;
  latest_date: string | null;
  regular_price: number | null;
  promo_price: number | null;
  promo_type: "sale" | "clearance" | null;
  first_date: string | null;
  change_1y_pct: number | null;
  change_5y_pct: number | null;
  p_up_1y: number | null;
  p_down_1y: number | null;
  up_pct: number | null;
  down_pct: number | null;
};

export type WineList = { total: number; items: WineSummary[] };

export type PricePoint = {
  date: string;
  regular_price: number;
  promo_price: number | null;
  promo_type: "sale" | "clearance" | null;
  vintage: string | null;
};

export type ForecastPoint = {
  date: string;
  p10: number;
  p50: number;
  p90: number;
  p_up: number;
  p_down: number;
  up_pct: number;
  down_pct: number;
};
export type Forecast = { model_version: string; algorithm: string; points: ForecastPoint[] };

type ChangeMetrics = { actual_rate_pct: number; predicted_rate_pct: number; roc_auc: number | null; avg_precision: number | null; brier_skill_vs_base_rate: number };

export type ModelInfo = {
  model_version: string;
  algorithm: string;
  trained_at: string;
  horizon: number;
  horizon_unit: string;
  source: string;
  metrics: {
    data_through: string;
    series: number;
    holdout_rows: number;
    share_price_changed_pct: number;
    interval_80_coverage_pct: number;
    price_change: Record<string, { up: ChangeMetrics; down: ChangeMetrics }>;
  };
};

export type ListParams = { style?: string; tier?: string; q?: string; featured?: boolean; sort?: string; offset?: number };

async function get<T>(path: string): Promise<T | null> {
  const res = await fetch(`${API_URL}${path}`, { next: { revalidate: 300 } });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

export const api = {
  wines: (params: ListParams) => {
    const qs = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== "" && v !== false)
        .map(([k, v]) => [k, String(v)]),
    );
    return get<WineList>(`/wines${qs.size ? `?${qs}` : ""}`);
  },
  wine: (slug: string) => get<WineSummary>(`/wines/${slug}`),
  prices: (slug: string) => get<PricePoint[]>(`/wines/${slug}/prices`),
  forecast: (slug: string) => get<Forecast>(`/wines/${slug}/forecast`),
  model: () => get<ModelInfo>("/model"),
};

export const usd = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: n >= 100 ? 0 : 2 });

export const pct = (p: number | null | undefined) => (p == null ? "—" : `${Math.round(p * 100)}%`);

export const quarterLabel = (d: string) => {
  const dt = new Date(`${d}T00:00:00`);
  return `Q${Math.floor(dt.getMonth() / 3) + 1} ${dt.getFullYear()}`;
};
