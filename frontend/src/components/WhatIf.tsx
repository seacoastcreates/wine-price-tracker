"use client";

import { useState } from "react";
import type { ForecastPoint } from "@/lib/api";
import { pct, quarterLabel, usd } from "@/lib/api";

type Promo = "keep" | "none" | "sale" | "clearance";
type Result = {
  model_version: string;
  latency_ms: number;
  baseline: ForecastPoint[];
  scenario: ForecastPoint[];
};

const PROMOS: { value: Promo; label: string }[] = [
  { value: "keep", label: "As listed" },
  { value: "none", label: "No promotion" },
  { value: "sale", label: "On sale" },
  { value: "clearance", label: "Clearance" },
];

function Shift({ from, to }: { from: number; to: number }) {
  const d = Math.round((to - from) * 100);
  const cls = d > 0 ? "text-up" : d < 0 ? "text-down" : "text-muted";
  return (
    <span className="tabular">
      {pct(from)} → <strong>{pct(to)}</strong>{" "}
      <span className={`text-xs ${cls}`}>{d === 0 ? "no change" : `${d > 0 ? "+" : ""}${d} pts`}</span>
    </span>
  );
}

export default function WhatIf({ slug, listPrice, promoType }: { slug: string; listPrice: number; promoType: string | null }) {
  const [promo, setPromo] = useState<Promo>("keep");
  const [discount, setDiscount] = useState(20);
  const [price, setPrice] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    const body = {
      promo,
      discount_pct: promo === "sale" || promo === "clearance" ? discount : 0,
      list_price: price ? Number(price) : null,
    };
    try {
      const res = await fetch(`/api/predict/${slug}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "The model could not run this scenario");
      setResult(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 card p-4">
      <h2 className="font-semibold">What if?</h2>
      <p className="mb-4 text-sm text-ink-2">
        Change today&apos;s price or promotion and the model re-scores this wine live.
        {promoType ? ` It is currently on ${promoType === "clearance" ? "clearance" : "sale"}.` : ""}
      </p>

      <div className="flex flex-wrap items-end gap-4">
        <div>
          <div className="mb-1 text-xs text-ink-2">Promotion</div>
          <div className="flex gap-1" role="group" aria-label="Promotion">
            {PROMOS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPromo(p.value)}
                aria-pressed={promo === p.value}
                className={`segment ${promo === p.value ? "segment-active" : ""}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {(promo === "sale" || promo === "clearance") && (
          <label className="text-sm">
            <div className="mb-1 text-xs text-ink-2">Discount: {discount}%</div>
            <input type="range" min={5} max={60} step={5} value={discount} onChange={(e) => setDiscount(Number(e.target.value))} />
          </label>
        )}

        <label className="text-sm">
          <div className="mb-1 text-xs text-ink-2">List price (today {usd(listPrice)})</div>
          <input
            type="number"
            min={1}
            step="0.01"
            placeholder={listPrice.toFixed(2)}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="field w-28"
          />
        </label>

        <button
          onClick={run}
          disabled={busy}
          className="btn-primary"
        >
          {busy ? "Running…" : "Run model"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-down">{error}</p>}

      {result && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="table-head border-b border-line text-left">
              <tr>
                <th className="py-2 font-medium">By</th>
                <th className="py-2 font-medium">Chance of a rise</th>
                <th className="py-2 font-medium">Chance of a cut</th>
                <th className="py-2 text-right font-medium">Median list price</th>
              </tr>
            </thead>
            <tbody>
              {result.scenario.map((s, i) => {
                const b = result.baseline[i];
                return (
                  <tr key={s.date} className="border-b border-line last:border-0">
                    <td className="py-2 tabular">{quarterLabel(s.date)}</td>
                    <td className="py-2"><Shift from={b.p_up} to={s.p_up} /></td>
                    <td className="py-2"><Shift from={b.p_down} to={s.p_down} /></td>
                    <td className="py-2 text-right tabular">{usd(s.p50)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">
            Scored live by model {result.model_version} in {result.latency_ms} ms. Arrows show the change from the
            wine as currently listed.
          </p>
        </div>
      )}
    </section>
  );
}
