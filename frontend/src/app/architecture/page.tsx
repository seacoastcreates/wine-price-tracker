import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Architecture" };

type BoxProps = { x: number; y: number; w: number; h: number; title: string; lines?: string[]; accent?: boolean; dashed?: boolean };

function Box({ x, y, w, h, title, lines = [], accent, dashed }: BoxProps) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        fill="var(--surface)"
        stroke={accent ? "var(--accent)" : "var(--axis)"}
        strokeWidth={accent ? 1.75 : 1}
        strokeDasharray={dashed ? "5 4" : undefined}
      />
      <text x={x + 12} y={y + 23} fontSize={13} fontWeight={600} fill="var(--ink)">
        {title}
      </text>
      {lines.map((l, i) => (
        <text key={l} x={x + 12} y={y + 41 + i * 15} fontSize={11} fill="var(--ink-2)">
          {l}
        </text>
      ))}
    </g>
  );
}

/** An arrow along a polyline. A surface-colored halo underneath keeps crossings legible. */
function Arrow({
  d,
  dashed,
  label,
  lx,
  ly,
  anchor = "middle",
}: {
  d: string;
  dashed?: boolean;
  label?: string | string[];
  lx?: number;
  ly?: number;
  anchor?: "start" | "middle" | "end";
}) {
  const color = dashed ? "var(--accent)" : "var(--ink-2)";
  return (
    <g>
      <path d={d} fill="none" stroke="var(--surface-2)" strokeWidth={6} />
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeDasharray={dashed ? "5 4" : undefined}
        markerEnd={dashed ? "url(#arrow-accent)" : "url(#arrow)"}
      />
      {label &&
        (Array.isArray(label) ? label : [label]).map((line, i) => (
          <text key={line} x={lx} y={(ly ?? 0) + i * 13} fontSize={10.5} fill="var(--muted)" textAnchor={anchor}>
            {line}
          </text>
        ))}
    </g>
  );
}

const COL = { src: 20, ing: 240, db: 480, ml: 700, reg: 940 };

function Diagram() {
  return (
    <svg
      viewBox="0 0 1120 520"
      role="img"
      aria-labelledby="arch-title arch-desc"
      className="w-full min-w-[900px]"
      fontFamily="var(--font-sans)"
    >
      <title id="arch-title">Cellar Index system architecture</title>
      <desc id="arch-desc">
        Offline, each quarter: public data sources are parsed and linked into PostgreSQL, three models are trained with a
        shared feature package, stored in a versioned model registry, and their results loaded back into the database.
        Online, on every request: the browser talks to the Next.js frontend, which calls the FastAPI model service; the
        service reads PostgreSQL and runs the active model in memory for live and what-if predictions.
      </desc>
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="var(--ink-2)" />
        </marker>
        <marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="var(--accent)" />
        </marker>
      </defs>

      {/* lanes */}
      <rect x={6} y={6} width={1108} height={338} rx={16} fill="var(--surface-2)" />
      <rect x={6} y={356} width={1108} height={156} rx={16} fill="var(--surface-2)" />
      <text x={20} y={30} fontSize={11} fontWeight={700} letterSpacing="0.12em" fill="var(--gold)">
        OFFLINE · QUARTERLY REFRESH (EventBridge Scheduler → refresh-aws.sh)
      </text>
      <text x={20} y={380} fontSize={11} fontWeight={700} letterSpacing="0.12em" fill="var(--gold)">
        ONLINE · EVERY REQUEST
      </text>

      {/* column titles */}
      {[
        [COL.src, "Sources"],
        [COL.ing, "Ingestion (backend/ingest)"],
        [COL.db, "Database"],
        [COL.ml, "Training (ml/)"],
        [COL.reg, "Model registry"],
      ].map(([x, t]) => (
        <text key={t} x={Number(x)} y={62} fontSize={11.5} fontWeight={600} fill="var(--muted)">
          {t}
        </text>
      ))}

      {/* offline: sources */}
      <Box x={COL.src} y={74} w={180} h={64} title="PLCB price lists" lines={["40 quarterly PDFs, 2016–2026"]} />
      <Box x={COL.src} y={154} w={180} h={64} title="NASA POWER" lines={["daily weather, 49 regions"]} />
      <Box x={COL.src} y={234} w={180} h={64} title="USDA crush reports" lines={["California supply, 2009–2025"]} />

      {/* offline: ingestion */}
      <Box x={COL.ing} y={74} w={200} h={64} title="Parse & classify" lines={["PDF text → wine, region,", "brand, grape"]} />
      <Box x={COL.ing} y={154} w={200} h={64} title="Link vintages" lines={["codes + names → 31k wines"]} />
      <Box x={COL.ing} y={234} w={200} h={64} title="Growing-season features" lines={["weather anomalies, crop supply"]} />

      {/* database */}
      <Box
        x={COL.db}
        y={74}
        w={180}
        h={224}
        accent
        title="PostgreSQL"
        lines={["wines", "price_observations", "regions", "model_runs", "forecasts", "vintage_outlook", "fair_prices"]}
      />

      {/* training */}
      <Box x={COL.ml} y={74} w={200} h={64} title="Export" lines={["training CSV + context tables"]} />
      <Box x={COL.ml} y={154} w={200} h={64} title="Train on SageMaker" lines={["price-change · next-vintage ·", "fair-price (Processing job)"]} />
      <Box x={COL.ml} y={234} w={200} h={64} dashed accent title="wineprice package" lines={["shared features & models"]} />

      {/* registry and load-back */}
      <Box x={COL.reg} y={74} w={160} h={80} title="Load results" lines={["forecasts, outlooks,", "fair prices, metrics"]} />
      <Box x={COL.reg} y={184} w={160} h={114} title="Model registry" lines={["versioned artifacts", "in S3", "one active version"]} />

      {/* offline arrows */}
      <Arrow d="M200 106 H240" />
      <Arrow d="M200 186 H220 V252 H240" />
      <Arrow d="M200 274 H240" />
      <Arrow d="M340 138 V154" />
      <Arrow d="M440 186 H480" />
      <Arrow d="M440 266 H462 V320 H682 V120 H700" label="weather & supply tables" lx={562} ly={334} anchor="end" />
      <Arrow d="M660 106 H700" label="export" lx={680} ly={98} />
      <Arrow d="M800 138 V154" />
      <Arrow d="M800 234 V218" dashed />
      <Arrow d="M900 186 H920 V241 H940" label="save" lx={920} ly={178} />
      <Arrow d="M1020 184 V154" />
      <Arrow d="M1090 74 V44 H570 V74" label="load forecasts & metrics into the database" lx={830} ly={40} />

      {/* online */}
      <Box x={COL.src} y={396} w={180} h={96} title="Browser" lines={["wine lists, charts,", "what-if panel"]} />
      <Box x={COL.ing} y={396} w={200} h={96} title="Next.js frontend" lines={["server-rendered pages", "/api/predict proxy for", "what-if requests"]} />
      <Box x={COL.db} y={396} w={180} h={96} accent title="FastAPI model service" lines={["data endpoints, OpenAPI docs", "live & what-if predictions", "explanations (Bedrock)"]} />
      <Box x={COL.reg} y={396} w={160} h={96} title="Active model" lines={["held in memory,", "hot-swapped when a new", "version is activated"]} />

      <Arrow d="M200 444 H240" label="HTTPS" lx={220} ly={436} />
      <Arrow d="M440 444 H480" label="JSON" lx={460} ly={436} />
      <Arrow d="M570 396 V298" label="SQL reads" lx={578} ly={390} anchor="start" />
      <Arrow d="M1020 298 V396" label="load artifact" lx={1062} ly={352} />
      <Arrow d="M940 460 H660" label="predict" lx={800} ly={474} />
      <Arrow d="M800 298 V426 H660" dashed label={["same feature code", "(parity-tested)"]} lx={810} ly={404} anchor="start" />
    </svg>
  );
}

const AWS = [
  ["Website + model service", "Live", "One EC2 t4g.small (Ubuntu, arm64): nginx routes / to Next.js and /api/v1 to FastAPI"],
  ["HTTPS and caching", "Live", "CloudFront in front; the server only accepts traffic from CloudFront, and has no SSH"],
  ["Database", "Live", "PostgreSQL on the same instance, restored from a dump at each deploy; nightly backups to S3"],
  ["Infrastructure", "Live", "AWS CDK (Python): every deploy rebuilds the server from source, reproducibly"],
  ["Cost guardrail", "Live", "AWS Budgets alerts at $5 and $20 a month"],
  ["Quarterly training", "Live", "EventBridge Scheduler -> SSM Run Command on the server -> SageMaker Processing job (ml.t3.xlarge) trains all three models"],
  ["Model registry", "Live", "Trained models are published to S3 (registry/<version>/) and hot-swapped by the API"],
  ["Plain-English explanations", "Live", "Amazon Bedrock (Amazon Nova Lite), generated per wine on request, cached and rate-limited"],
];

export default function ArchitecturePage() {
  return (
    <>
      <div className="eyebrow">System design</div>
      <h1 className="display mt-2 text-4xl font-semibold sm:text-5xl">Architecture</h1>
      <p className="mt-3 mb-8 max-w-3xl text-lg text-ink-2">
        Two paths share one feature pipeline. Each quarter an offline refresh turns public data into a database and
        three trained models; on every page view the model service reads that database and runs the active model live.
      </p>

      <section className="card mb-4 overflow-x-auto p-4">
        <Diagram />
      </section>
      <div className="mb-8 flex flex-wrap gap-6 text-sm text-ink-2">
        <span className="flex items-center gap-2">
          <svg width="28" height="8" aria-hidden="true">
            <path d="M0 4 H26" stroke="var(--ink-2)" strokeWidth="1.5" />
          </svg>
          Data flow
        </span>
        <span className="flex items-center gap-2">
          <svg width="28" height="8" aria-hidden="true">
            <path d="M0 4 H26" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="5 4" />
          </svg>
          Shared code
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-3 w-4 rounded-sm border-2 border-accent" /> Core services
        </span>
      </div>

      <section className="mb-8 grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <h2 className="font-semibold">Offline: the quarterly refresh</h2>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
            <li>Download the state&apos;s quarterly price-list PDFs, NASA POWER weather and USDA crush reports.</li>
            <li>Parse the PDFs, identify wines, and extract region, brand, grape and classification from names.</li>
            <li>Link the same wine across quarters and name changes; each vintage is its own wine.</li>
            <li>Export training data with context tables and train three models using the shared wineprice package.</li>
            <li>Evaluate on held-out time periods, save a versioned artifact, and load its results into the database.</li>
          </ol>
        </div>
        <div className="card p-5">
          <h2 className="font-semibold">Online: every request</h2>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
            <li>The browser loads pages rendered by Next.js.</li>
            <li>Next.js calls the FastAPI model service for wines, prices, forecasts and model metrics.</li>
            <li>The service reads PostgreSQL and keeps the active model in memory.</li>
            <li>What-if requests re-run the model live on the wine&apos;s history with the changed price or promotion.</li>
            <li>A parity test checks that live predictions match the batch forecasts exactly.</li>
          </ol>
        </div>
      </section>

      <section className="card mb-8 overflow-x-auto">
        <h2 className="px-5 pt-5 font-semibold">How it maps to AWS</h2>
        <p className="px-5 pb-3 text-sm text-ink-2">
          What runs where on AWS, chosen to keep running costs low (about $17 a month).
        </p>
        <table className="w-full min-w-[640px] text-sm">
          <thead className="table-head border-y border-line text-left">
            <tr>
              <th className="px-5 py-2 font-medium">Component</th>
              <th className="px-5 py-2 font-medium">Status</th>
              <th className="px-5 py-2 font-medium">How it runs</th>
            </tr>
          </thead>
          <tbody>
            {AWS.map(([c, status, aws]) => (
              <tr key={c} className="border-b border-line last:border-0">
                <td className="px-5 py-2 font-medium">{c}</td>
                <td className="px-5 py-2">
                  <span className={status === "Live" ? "badge" : "text-muted"}>{status}</span>
                </td>
                <td className="px-5 py-2 text-ink-2">{aws}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <p className="text-sm text-ink-2">
        Details on the models themselves are on <Link className="underline hover:text-accent" href="/model">How it works</Link>.
      </p>
    </>
  );
}
