import type { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** Forwards what-if requests to the model API, so the browser never needs the API's address. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/predict/[slug]">) {
  const { slug } = await ctx.params;
  const res = await fetch(`${API_URL}/wines/${encodeURIComponent(slug)}/predict`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}
