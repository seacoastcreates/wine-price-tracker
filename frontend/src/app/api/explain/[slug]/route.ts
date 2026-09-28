import type { NextRequest } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function forward(method: "GET" | "POST", slug: string) {
  const res = await fetch(`${API_URL}/wines/${encodeURIComponent(slug)}/explanation`, { method, cache: "no-store" });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}

/** Cached explanation, if one exists. */
export async function GET(_req: NextRequest, ctx: RouteContext<"/api/explain/[slug]">) {
  return forward("GET", (await ctx.params).slug);
}

/** Generate (or return the cached) explanation via the model service. */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/explain/[slug]">) {
  return forward("POST", (await ctx.params).slug);
}
