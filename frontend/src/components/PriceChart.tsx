"use client";

import { useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastPoint, PricePoint } from "@/lib/api";
import { pct, quarterLabel, usd } from "@/lib/api";

type Row = {
  date: string;
  ts: number;
  price?: number;
  promo?: number;
  promoType?: string | null;
  p50?: number;
  band?: [number, number];
  fc?: ForecastPoint;
};

const RANGES = { "2Y": 2, "5Y": 5, All: 99 } as const;
const ts = (d: string) => new Date(`${d}T00:00:00`).getTime();

function Key({ kind, label }: { kind: "history" | "forecast" | "band" | "sale"; label: string }) {
  const swatch =
    kind === "band" ? (
      <span className="inline-block h-3 w-4 rounded-sm" style={{ background: "var(--series-forecast)", opacity: 0.18 }} />
    ) : kind === "sale" ? (
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--series-sale)" }} />
    ) : (
      <span className="inline-block h-0.5 w-4 rounded" style={{ background: `var(--series-${kind})` }} />
    );
  return (
    <span className="flex items-center gap-2 text-sm text-ink-2">
      {swatch}
      {label}
    </span>
  );
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm shadow-sm">
      <div className="mb-1 text-muted">
        {quarterLabel(r.date)}
      </div>
      {r.price != null && <div className="tabular">List price <strong>{usd(r.price)}</strong></div>}
      {r.promo != null && (
        <div className="tabular">
          {r.promoType === "clearance" ? "Clearance" : "Sale"} price <strong>{usd(r.promo)}</strong>
        </div>
      )}
      {r.fc && (
        <>
          <div className="tabular">Forecast <strong>{usd(r.fc.p50)}</strong></div>
          <div className="tabular text-ink-2">80% range {usd(r.fc.p10)} – {usd(r.fc.p90)}</div>
          <div className="tabular text-ink-2">
            Chance higher {pct(r.fc.p_up)} · lower {pct(r.fc.p_down)}
          </div>
        </>
      )}
    </div>
  );
}

export default function PriceChart({ prices, forecast }: { prices: PricePoint[]; forecast: ForecastPoint[] }) {
  const [range, setRange] = useState<keyof typeof RANGES>("All");

  const rows = useMemo<Row[]>(() => {
    const last = prices.at(-1);
    const cutoff = last ? ts(last.date) - RANGES[range] * 365.25 * 86400e3 : 0;
    const hist: Row[] = prices
      .filter((p) => ts(p.date) >= cutoff - 7 * 86400e3)
      .map((p) => ({
        date: p.date,
        ts: ts(p.date),
        price: p.regular_price,
        promo: p.promo_price ?? undefined,
        promoType: p.promo_type,
      }));
    const anchor = hist.at(-1);
    // Anchor the forecast to the latest list price so the two lines connect.
    if (anchor && forecast.length) Object.assign(anchor, { p50: anchor.price, band: [anchor.price, anchor.price] });
    return [
      ...hist,
      ...forecast.map((f) => ({ date: f.date, ts: ts(f.date), p50: f.p50, band: [f.p10, f.p90] as [number, number], fc: f })),
    ];
  }, [prices, forecast, range]);

  const hasSales = rows.some((r) => r.promo != null);
  // One tick per January so each year is labelled exactly once.
  const yearTicks = useMemo(() => {
    if (!rows.length) return [];
    const first = new Date(rows[0].ts).getFullYear() + 1;
    const last = new Date(rows[rows.length - 1].ts).getFullYear();
    return Array.from({ length: Math.max(last - first + 1, 0) }, (_, i) => new Date(first + i, 0, 1).getTime());
  }, [rows]);

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-4">
          <Key kind="history" label="List price" />
          {hasSales && <Key kind="sale" label="Sale / clearance price" />}
          <Key kind="forecast" label="Forecast (median)" />
          <Key kind="band" label="80% forecast range" />
        </div>
        <div className="flex gap-1" role="group" aria-label="Time range">
          {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              aria-pressed={range === r}
              className={`segment ${range === r ? "segment-active" : ""}`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              ticks={yearTicks}
              tickFormatter={(v: number) => new Date(v).getFullYear().toString()}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--axis)" }}
              tickLine={false}
            />
            <YAxis
              domain={[(min: number) => Math.floor(min * 0.9), (max: number) => Math.ceil(max * 1.05)]}
              tickFormatter={(v: number) => usd(v)}
              width={64}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
            <Area dataKey="band" stroke="none" fill="var(--series-forecast)" fillOpacity={0.18} isAnimationActive={false} />
            <Line
              dataKey="price"
              type="stepAfter"
              stroke="var(--series-history)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              strokeLinejoin="round"
              isAnimationActive={false}
            />
            <Scatter dataKey="promo" fill="var(--series-sale)" stroke="var(--surface)" strokeWidth={2} isAnimationActive={false} />
            <Line
              dataKey="p50"
              stroke="var(--series-forecast)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              strokeLinejoin="round"
              strokeLinecap="round"
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-ink-2">Show prices and forecast as a table</summary>
        <table className="tabular mt-2 w-full max-w-2xl">
          <thead className="text-left text-ink-2">
            <tr>
              <th className="py-1 font-medium">Quarter</th>
              <th className="py-1 text-right font-medium">List</th>
              <th className="py-1 text-right font-medium">Sale</th>
              <th className="py-1 text-right font-medium">Forecast (80% range)</th>
              <th className="py-1 text-right font-medium">Chance higher</th>
            </tr>
          </thead>
          <tbody>
            {[...rows].reverse().map((r) => (
              <tr key={r.date} className="border-t border-line">
                <td className="py-1">{quarterLabel(r.date)}</td>
                <td className="py-1 text-right">{r.price != null ? usd(r.price) : ""}</td>
                <td className="py-1 text-right">{r.promo != null ? usd(r.promo) : ""}</td>
                <td className="py-1 text-right">{r.fc ? `${usd(r.fc.p50)} (${usd(r.fc.p10)}–${usd(r.fc.p90)})` : ""}</td>
                <td className="py-1 text-right">{r.fc ? pct(r.fc.p_up) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
