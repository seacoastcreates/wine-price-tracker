const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type WineSummary = {
  slug: string;
  family: string;
  name: string;
  vintage: string;
  region: string | null;
  size: string;
  style: string;
  tier: string;
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
  fair_price: number | null;
  fair_low: number | null;
  fair_high: number | null;
  value_pct: number | null;
};

export type WineList = { total: number; items: WineSummary[] };

export type PricePoint = {
  date: string;
  regular_price: number;
  promo_price: number | null;
  promo_type: "sale" | "clearance" | null;
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
    feature_importance?: { feature: string; auc_drop: number }[];
    feature_groups?: string[];
    ablation?: {
      external_data?: AblationRun;
      brand_attributes?: AblationRun;
      brand_attributes_earlier_holdout?: { holdout: string } & Record<string, Record<string, number> | string>;
    };
    fair_model?: {
      folds: number;
      variants: Record<string, FairEval>;
    };
    vintage_model?: {
      transitions: number;
      folds: number;
      chosen_groups: string[];
      same_price_mae_by_fold: Record<string, number>;
      rolling_cv: Record<string, VintageCv>;
    };
  };
};

export type ListParams = {
  style?: string;
  tier?: string;
  q?: string;
  featured?: boolean;
  investor?: boolean;
  sort?: string;
  dir?: "asc" | "desc";
  offset?: number;
};

export type Insights = {
  drinking_window: { opens: number; closes: number; status: "before" | "in" | "past"; basis: string } | null;
  next_vintage: {
    next_vintage: number;
    p_up: number;
    p_down: number;
    p10_pct: number;
    p50_pct: number;
    p90_pct: number;
  } | null;
};

type AblationRow = { n: number; positives: number; roc_auc?: number; brier_skill?: number };
type AblationRun = Record<string, Record<string, AblationRow>>;
type FairEval = {
  wines: number;
  median_abs_pct_error: number;
  r2_log: number;
  interval_80_coverage_pct: number;
  interval_80_coverage_pct_calibrated?: number;
};
type VintageCv = {
  mae: number;
  auc: number;
  mae_vs_current: number;
  folds_mae_better: number;
  auc_vs_current: number;
  folds_auc_better: number;
};

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
  insights: (slug: string) => get<Insights>(`/wines/${slug}/insights`),
  vintages: (slug: string) => get<WineSummary[]>(`/wines/${slug}/vintages`),
  prices: (slug: string) => get<PricePoint[]>(`/wines/${slug}/prices`),
  forecast: (slug: string) => get<Forecast>(`/wines/${slug}/forecast`),
  model: () => get<ModelInfo>("/model"),
};

export const usd = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: n >= 100 ? 0 : 2 });

/** "Caymus Vineyards Cabernet Sauvignon 2020", or the bare name for non-vintage wines. */
export const wineTitle = (w: { name: string; vintage: string }) => (w.vintage === "NV" ? w.name : `${w.name} ${w.vintage}`);

export const pct = (p: number | null | undefined) =>
  p == null ? "—" : p > 0 && p < 0.005 ? "<1%" : `${Math.round(p * 100)}%`;

export const quarterLabel = (d: string) => {
  const dt = new Date(`${d}T00:00:00`);
  return `Q${Math.floor(dt.getMonth() / 3) + 1} ${dt.getFullYear()}`;
};
