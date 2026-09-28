import Link from "next/link";
import { api } from "@/lib/api";
import { SourceNote, StatTile } from "@/components/ui";

const FEATURE_LABELS: Record<string, string> = {
  lr_1: "Price change over the last quarter",
  lr_2: "Price change over 2 quarters",
  lr_4: "Price change over 1 year",
  lr_8: "Price change over 2 years",
  vol_4: "Recent price volatility",
  changes_8: "Number of price changes in 2 years",
  periods_since_change: "Quarters since the last price change",
  age: "Quarters on the price list",
  log_price: "Price level",
  on_sale: "Currently on sale",
  on_clearance: "Currently on clearance",
  discount: "Size of the current discount",
  vintage_age: "Years since the vintage",
  is_nv: "Non-vintage (or vintage not listed)",
  target_period_of_year: "Quarter of the year",
  style: "Style (red, white, …)",
  tier: "Price tier",
  years_to_window: "Years until the drinking window opens",
  years_past_window: "Years past the drinking window",
  in_window: "Inside its drinking window",
  brand_n_others: "Other wines from the same brand",
  brand_up_1q: "Share of the brand's wines raised last quarter",
  brand_up_4q: "Share of the brand's wines raised in the last year",
  brand_down_4q: "Share of the brand's wines cut in the last year",
  brand_rel_price: "Price vs the brand's other wines",
  grape: "Grape variety",
  classification: "Classification",
};

// Holdout comparisons with enough real price moves to be meaningful (see ablation.py).
const ABLATION_ROWS: [string, string][] = [
  ["up | all wines | h=1", "Rises, all wines, next quarter"],
  ["up | all wines | h=4", "Rises, all wines, within a year"],
  ["down | all wines | h=4", "Cuts, all wines, within a year"],
  ["up | vintage-dated | h=4", "Rises, vintage-dated wines, within a year"],
  ["up | California | h=4", "Rises, California wines, within a year"],
];

function AblationTable({
  title,
  intro,
  run,
  sets,
  extraRows = [],
  conclusion,
}: {
  title: string;
  intro: React.ReactNode;
  run: Record<string, Record<string, { positives: number; roc_auc?: number }>>;
  sets: string[];
  extraRows?: [string, string][];
  conclusion: string;
}) {
  const present = sets.filter((k) => run[k]);
  return (
    <section className="mb-8 overflow-x-auto card">
      <h2 className="px-4 pt-4 font-semibold">{title}</h2>
      <p className="px-4 pb-3 text-sm text-ink-2">
        {intro} Cells show ranking skill (ROC AUC) on the holdout year; the number in brackets is how many real price
        moves the comparison contains.
      </p>
      <table className="tabular w-full min-w-[760px] text-sm">
        <thead className="table-head border-y border-line text-left">
          <tr>
            <th className="px-4 py-2 font-medium">Comparison</th>
            {present.map((k) => (
              <th key={k} className="px-4 py-2 text-right font-medium">{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...ABLATION_ROWS, ...extraRows].map(([key, label]) => {
            const vals = present.map((k) => run[k]?.[key]?.roc_auc ?? null);
            if (vals.every((v) => v == null)) return null;
            const best = Math.max(...vals.map((v) => v ?? -1));
            return (
              <tr key={key} className="border-b border-line last:border-0">
                <td className="px-4 py-2">
                  {label} <span className="text-muted">({run[present[0]]?.[key]?.positives ?? "—"})</span>
                </td>
                {vals.map((v, i) => (
                  <td key={present[i]} className={`px-4 py-2 text-right ${v === best ? "font-semibold text-ink" : "text-ink-2"}`}>
                    {v?.toFixed(3) ?? "—"}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-4 py-3 text-sm text-ink-2">{conclusion}</p>
    </section>
  );
}

export default async function ModelPage() {
  const model = await api.model();
  if (!model) return <p className="text-ink-2">No model has been trained yet.</p>;
  const m = model.metrics;
  const horizons = Object.keys(m.price_change).sort();
  const importance = (m.feature_importance ?? []).filter((f) => f.auc_drop > 0);
  const maxDrop = Math.max(...importance.map((f) => f.auc_drop), 1e-9);

  return (
    <>
      <div className="eyebrow">Methods and results</div>
      <h1 className="display mt-2 text-4xl font-semibold sm:text-5xl">How the model works</h1>
      <p className="mt-2 mb-6 max-w-3xl text-ink-2">
        Wine list prices rarely change, so the model predicts <em>whether</em> each wine&apos;s list price will rise or
        fall over the next four quarters, and by how much. One model is trained across all {m.series.toLocaleString()}{" "}
        wines and scored on the most recent year, which it never saw during training.{" "}
        <Link className="whitespace-nowrap font-medium text-accent underline underline-offset-2 hover:text-accent-hover" href="/architecture">
          See the full system architecture →
        </Link>
      </p>

      <section className="mb-8 grid gap-3 sm:grid-cols-3">
        <StatTile label="Model version" value={<span className="text-base">{model.model_version}</span>} sub={`Data through ${m.data_through}`} />
        <StatTile
          label="How often list prices change"
          value={`${m.share_price_changed_pct}%`}
          sub={`of wines get a new list price in a typical quarter. Guessing "no change" is right about ${Math.round(100 - m.share_price_changed_pct)}% of the time, so the model's job is to spot the few that will move.`}
        />
        <StatTile
          label="How reliable the price ranges are"
          value={`${m.interval_80_coverage_pct}%`}
          sub={`of actual prices landed inside the forecast's 80% range. The target is 80%, so ${
            m.interval_80_coverage_pct > 85
              ? "the ranges are wider (more cautious) than they need to be."
              : m.interval_80_coverage_pct < 75
                ? "the ranges are too narrow."
                : "the ranges are about right."
          }`}
        />
      </section>

      <section className="mb-8 overflow-x-auto card">
        <h2 className="px-4 pt-4 font-semibold">Accuracy on the holdout year</h2>
        <p className="px-4 pb-3 text-sm text-ink-2">
          Ranking accuracy is measured as the area under the receiver operating characteristic curve (ROC AUC): the chance
          that the model scores a wine whose price actually changed above one whose price didn&apos;t. 0.5 is a coin flip
          and 1.0 is perfect. Average precision shows how often the wines the model flags really moved; compare it with
          the share of all wines that moved, in brackets.
        </p>
        <table className="tabular w-full min-w-[720px] text-sm">
          <thead className="table-head border-y border-line text-left">
            <tr>
              <th className="px-4 py-2 font-medium">Horizon</th>
              <th className="px-4 py-2 text-right font-medium">Rise: ROC AUC</th>
              <th className="px-4 py-2 text-right font-medium">Rise: avg precision (share that rose)</th>
              <th className="px-4 py-2 text-right font-medium">Rise: predicted vs actual rate</th>
              <th className="px-4 py-2 text-right font-medium">Cut: ROC AUC</th>
            </tr>
          </thead>
          <tbody>
            {horizons.map((h) => {
              const up = m.price_change[h].up;
              const down = m.price_change[h].down;
              return (
                <tr key={h} className="border-b border-line last:border-0">
                  <td className="px-4 py-2">{h} quarter{h === "1" ? "" : "s"} ahead</td>
                  <td className="px-4 py-2 text-right">{up.roc_auc ?? "—"}</td>
                  <td className="px-4 py-2 text-right">
                    {up.avg_precision ?? "—"} ({(up.actual_rate_pct / 100).toFixed(3)})
                  </td>
                  <td className="px-4 py-2 text-right">
                    {up.predicted_rate_pct}% vs {up.actual_rate_pct}%
                  </td>
                  <td className="px-4 py-2 text-right">{down.roc_auc ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {importance.length > 0 && (
        <section className="mb-8 card p-4">
          <h2 className="font-semibold">What drives the prediction of a price rise</h2>
          <p className="mb-4 text-sm text-ink-2">
            Permutation importance: how much ranking skill (ROC AUC) is lost when a feature&apos;s values are shuffled.
            Longer bars matter more.
          </p>
          <div className="grid gap-2 text-sm sm:grid-cols-[18rem_1fr_4rem]">
            {importance.map((f) => (
              <div key={f.feature} className="contents">
                <div className="text-ink-2">{FEATURE_LABELS[f.feature] ?? f.feature}</div>
                <div className="flex items-center">
                  <span
                    className="block h-3 rounded-r"
                    style={{ width: `${(f.auc_drop / maxDrop) * 100}%`, background: "var(--series-history)" }}
                  />
                </div>
                <div className="tabular text-right">{f.auc_drop.toFixed(3)}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {m.ablation?.external_data && (
        <AblationTable
          title="Experiment 1: external data (price-change model)"
          intro={
            <>
              Each column retrains the model with one extra group of features, using the same holdout year and seed:
              growing-season <strong>weather</strong> (NASA POWER reanalysis, anomalies vs each region&apos;s 1991–2020
              normal), California <strong>supply</strong> (USDA grape crush report), and each wine&apos;s typical{" "}
              <strong>drinking window</strong>.
            </>
          }
          run={m.ablation.external_data}
          sets={["base", "+weather", "+supply", "+window", "all"]}
          conclusion="Adopted: drinking window. It helps vintage-dated wines with no downside. Weather helps predict cuts but hurts the headline rise predictions; supply is too small to matter."
        />
      )}

      {m.ablation?.brand_attributes && (
        <AblationTable
          title="Experiment 2: brand momentum and wine attributes"
          intro={
            <>
              <strong>Brand</strong>: what the producer did to its other wines (share raised or cut last quarter and
              year, and this wine&apos;s price vs the brand&apos;s). <strong>Attributes</strong>: grape variety and
              classification (Grand Cru, Reserva, …) parsed from the name. Baseline is the current production model.
            </>
          }
          run={m.ablation.brand_attributes}
          sets={["current", "+brand", "+attributes", "+both"]}
          extraRows={[["up | brand with 2+ wines | h=4", "Rises, brands with 2+ wines, within a year"]]}
          conclusion={
            m.ablation.brand_attributes_earlier_holdout
              ? `Brand momentum improved rise ranking on the latest holdout year, but on an earlier one (${m.ablation.brand_attributes_earlier_holdout.holdout.replace(/ \(.*\)$/, "")}, trained only on earlier data) it made every comparison worse (rises within a year ${(m.ablation.brand_attributes_earlier_holdout.current as Record<string, number>)["up | all wines | h=4"]} → ${(m.ablation.brand_attributes_earlier_holdout["+brand"] as Record<string, number>)["up | all wines | h=4"]}). The gain isn't reliable, likely because the April 2023 statewide increase teaches the model that whole brands move together. Attributes hurt on both. Neither is adopted.`
              : "Neither is adopted."
          }
        />
      )}

      {m.vintage_model?.rolling_cv && (
        <section className="mb-8 overflow-x-auto card">
          <h2 className="px-4 pt-4 font-semibold">Next-vintage model</h2>
          <p className="px-4 pb-3 text-sm text-ink-2">
            Predicts how a wine&apos;s next vintage will be priced against the current one, from{" "}
            {m.vintage_model.transitions.toLocaleString()} past vintage changes. Feature sets are compared over{" "}
            {m.vintage_model.folds} rolling one-year test windows, each trained only on earlier data. Error is the mean
            absolute log price change (lower is better); the &quot;same price&quot; guess scores{" "}
            {Math.min(...Object.values(m.vintage_model.same_price_mae_by_fold)).toFixed(3)}–
            {Math.max(...Object.values(m.vintage_model.same_price_mae_by_fold)).toFixed(3)} across windows.
          </p>
          <table className="tabular w-full min-w-[640px] text-sm">
            <thead className="table-head border-y border-line text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Features</th>
                <th className="px-4 py-2 text-right font-medium">Error (mean)</th>
                <th className="px-4 py-2 text-right font-medium">vs current</th>
                <th className="px-4 py-2 text-right font-medium">Windows better</th>
                <th className="px-4 py-2 text-right font-medium">Rise ROC AUC</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.vintage_model.rolling_cv)
                .sort(([a], [b]) => (a === "current" ? -1 : b === "current" ? 1 : 0))
                .map(([k, r]) => (
                <tr key={k} className="border-b border-line last:border-0">
                  <td className="px-4 py-2">{k === "current" ? "current (base + supply)" : k}</td>
                  <td className="px-4 py-2 text-right">{r.mae.toFixed(4)}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{k === "current" ? "—" : `${r.mae_vs_current > 0 ? "+" : ""}${r.mae_vs_current.toFixed(4)}`}</td>
                  <td className="px-4 py-2 text-right text-ink-2">{k === "current" ? "—" : `${r.folds_mae_better}/${m.vintage_model!.folds}`}</td>
                  <td className="px-4 py-2 text-right">{r.auc.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-4 py-3 text-sm text-ink-2">
            Adopted: <strong>{m.vintage_model.chosen_groups.join(", ") || "base features only"}</strong>. California
            supply lowered error in every window in an earlier round; weather&apos;s effect flipped sign between windows,
            and brand momentum and wine attributes didn&apos;t help (attributes overfit the ~4,900 transitions).
          </p>
        </section>
      )}

      {m.fair_model && (
        <section className="mb-8 overflow-x-auto card">
          <h2 className="px-4 pt-4 font-semibold">Fair-price model</h2>
          <p className="px-4 pb-3 text-sm text-ink-2">
            Estimates what a wine should cost from what it is: region, grape, classification, style, bottle size, age
            of the vintage, words in its name, and the producer&apos;s price level from its other wines. Each wine is
            priced by a model that never saw it or any of its vintages ({m.fair_model.folds}-fold cross-validation
            grouped by wine), so the gap between shelf price and fair price is an honest value signal. Scores are on
            all {m.fair_model.variants.full?.wines.toLocaleString()} wines; R² is the share of variation in (log)
            price the model explains.
          </p>
          <table className="tabular w-full min-w-[640px] text-sm">
            <thead className="table-head border-y border-line text-left">
              <tr>
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 text-right font-medium">Typical error</th>
                <th className="px-4 py-2 text-right font-medium">R²</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.fair_model.variants).map(([k, r]) => (
                <tr key={k} className={`border-b border-line last:border-0 ${k === "full" ? "font-semibold" : ""}`}>
                  <td className="px-4 py-2">{k === "full" ? "Full model (used)" : k}</td>
                  <td className="px-4 py-2 text-right">{r.median_abs_pct_error}%</td>
                  <td className="px-4 py-2 text-right">{r.r2_log.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-4 py-3 text-sm text-ink-2">
            Typical error is the median absolute percentage error. Both the name text and the producer&apos;s price
            level add real information; vintage weather adds none, consistent with the other experiments: retail prices
            follow producer and appellation more than the growing season.
            {m.fair_model.variants.full?.interval_80_coverage_pct_calibrated != null &&
              ` The 80% fair range covers ${m.fair_model.variants.full.interval_80_coverage_pct_calibrated}% of real prices after calibration; a wine is flagged as a deal or a premium only when its price falls outside that range.`}
          </p>
        </section>
      )}

      <section className="mb-8 card p-4 text-sm text-ink-2">
        <h2 className="mb-2 font-semibold text-ink">Serving</h2>
        <p>
          The training job writes batch forecasts for every wine. The API also loads the same model artifact from the
          model registry and scores wines on demand: that powers the what-if panel on each wine page. Both paths share
          one feature pipeline, and an automated parity test checks that online predictions match the batch
          forecasts.
        </p>
      </section>

      <SourceNote />
    </>
  );
}
