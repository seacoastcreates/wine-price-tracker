"use client";

import { useEffect, useState } from "react";

type Explanation = { text: string; model_id: string; created_at: string; cached: boolean };

/** "Why this outlook?": a plain-English explanation written by Amazon Nova on Amazon Bedrock from this
 *  wine's own numbers. Generated only on request and cached per wine and model version. */
export default function Explain({ slug }: { slug: string }) {
  const [data, setData] = useState<Explanation | null>(null);
  const [state, setState] = useState<"loading" | "idle" | "working" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`/api/explain/${slug}`)
      .then(async (r) => (r.ok ? ((await r.json()) as Explanation) : null))
      .then((d) => {
        if (!live) return;
        setData(d);
        setState("idle");
      })
      .catch(() => live && setState("idle"));
    return () => {
      live = false;
    };
  }, [slug]);

  async function generate() {
    setState("working");
    setError(null);
    try {
      const res = await fetch(`/api/explain/${slug}`, { method: "POST" });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Could not generate an explanation");
      setData(json);
      setState("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState("error");
    }
  }

  return (
    <section className="card mt-6 p-5">
      <h2 className="font-semibold">Why this outlook?</h2>
      {data ? (
        <>
          <p className="mt-2 max-w-3xl leading-relaxed text-ink">{data.text}</p>
          <p className="mt-2 text-xs text-muted">
            Written by Amazon Nova (Amazon Bedrock) from this wine&apos;s own numbers above; it explains the
            models&apos; output and does not make its own predictions.
          </p>
        </>
      ) : (
        <>
          <p className="mt-1 mb-3 text-sm text-ink-2">
            Get a plain-English explanation of this wine&apos;s forecast, fair price and vintage outlook, written by
            Amazon Nova on Amazon Bedrock using only the numbers on this page.
          </p>
          <button onClick={generate} disabled={state === "working" || state === "loading"} className="btn-primary">
            {state === "working" ? "Writing…" : "Explain this outlook"}
          </button>
          {error && <p className="mt-3 text-sm text-down">{error}</p>}
        </>
      )}
    </section>
  );
}
