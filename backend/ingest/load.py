"""Load parsed PLCB price lists into Postgres.

Keeps wine ids stable across reloads (upsert by slug) and replaces all 'pa_plcb' observations.

    python -m ingest.load
"""

import csv
import io
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from app.db import get_engine
from ingest.classify import is_wine, product_key, style_of, tier_of, VINTAGE
from ingest.pa_plcb import OUT as PRICES_CSV

SOURCE = "pa_plcb"
FEATURED = Path(__file__).resolve().parents[1] / "db" / "featured.json"


def vintage_rank(v: str) -> int:
    return int(v) if v.isdigit() else 0


def display_name(desc: str) -> str:
    return " ".join(VINTAGE.sub("", desc.replace("Nonvintage", "")).split())


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def build() -> tuple[dict, list[dict]]:
    """Returns wines keyed by slug, and one observation per (wine, report date).

    A wine is a connected group of rows that share either a PLCB code (same SKU, even when the
    description was rewritten in the Oct 2023 format change) or a normalized name at the same
    size (same wine, new vintage code)."""
    rows = []
    with PRICES_CSV.open() as f:
        for r in csv.DictReader(f):
            if is_wine(r["description"], r["size"]):
                rows.append(r)

    uf = UnionFind()
    for r in rows:
        uf.union(f"code:{r['code']}|{r['size']}", f"name:{product_key(r['description'], r['size'])}")
    # Featured wines flagged merge_all have been renamed more than once; join every variant.
    for i, item in enumerate(json.loads(FEATURED.read_text())):
        if item.get("merge_all"):
            for r in rows:
                if r["size"] == "750 ML" and matches(r["description"], item):
                    uf.union(f"code:{r['code']}|{r['size']}", f"featured:{i}")
    group = {id(r): uf.find(f"code:{r['code']}|{r['size']}") for r in rows}

    per_report: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (group[id(r)], r["report_date"])
        # When several vintages are listed at once, follow the newest one.
        cur = per_report.get(key)
        if cur is None or vintage_rank(r["vintage"]) > vintage_rank(cur["vintage"]):
            per_report[key] = r

    by_group: dict[str, list[dict]] = defaultdict(list)
    for (g, _), r in per_report.items():
        by_group[g].append(r)

    latest_report = max(d for _, d in per_report)
    wines, observations = {}, []
    for obs in by_group.values():
        obs.sort(key=lambda r: r["report_date"])
        last = obs[-1]
        slug = product_key(last["description"], last["size"])
        observations += [dict(r, slug=slug) for r in obs]
        wines[slug] = {
            "slug": slug,
            "name": display_name(last["description"]),
            "size": last["size"],
            "style": style_of(last["description"]),
            "tier": tier_of(float(last["regular_price"])),
            "latest_vintage": last["vintage"] or None,
            "source_codes": sorted({r["code"] for r in obs}),
            "is_active": last["report_date"] == latest_report,
        }
    return wines, observations


def matches(name: str, item: dict) -> bool:
    name = name.lower()
    return all(t.lower() in name for t in item["match"]) and not any(t.lower() in name for t in item.get("exclude", []))


def featured_slugs(wines: dict, obs: list[dict]) -> set[str]:
    """Match each featured wine to the 750 ML product with the longest history."""
    quarters = defaultdict(int)
    for r in obs:
        quarters[r["slug"]] += 1
    chosen = set()
    for item in json.loads(FEATURED.read_text()):
        candidates = [s for s, w in wines.items() if w["size"] == "750 ML" and matches(w["name"], item)]
        if candidates:
            chosen.add(max(candidates, key=lambda s: (wines[s]["is_active"], quarters[s])))
        else:
            print(f"  featured wine not found: {item['match']}")
    return chosen


def main() -> None:
    wines, obs = build()
    featured = featured_slugs(wines, obs)
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql((Path(__file__).resolve().parents[1] / "db" / "schema.sql").read_text())
        conn.execute(text("UPDATE wines SET is_featured = FALSE"))
        conn.execute(
            text(
                """
                INSERT INTO wines (slug, name, size, style, tier, latest_vintage, source_codes, is_featured, is_active)
                VALUES (:slug, :name, :size, :style, :tier, :latest_vintage, :source_codes, :is_featured, :is_active)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name, size = EXCLUDED.size, style = EXCLUDED.style, tier = EXCLUDED.tier,
                    latest_vintage = EXCLUDED.latest_vintage, source_codes = EXCLUDED.source_codes,
                    is_featured = EXCLUDED.is_featured, is_active = EXCLUDED.is_active
                """
            ),
            [dict(w, is_featured=s in featured) for s, w in wines.items()],
        )
        ids = dict(conn.execute(text("SELECT slug, id FROM wines")).all())
        conn.execute(text("DELETE FROM price_observations WHERE source = :s"), {"s": SOURCE})

        buf = io.StringIO()
        w = csv.writer(buf)
        for r in obs:
            w.writerow([ids[r["slug"]], r["report_date"], SOURCE, r["code"], r["vintage"] or None,
                        r["regular_price"], r["promo_price"] or None, r["promo_type"] or None,
                        r["sale_start"] or None, r["sale_end"] or None])
        raw = conn.connection.driver_connection
        with raw.cursor().copy(
            "COPY price_observations (wine_id, observed_on, source, source_code, vintage, regular_price, "
            "promo_price, promo_type, sale_start, sale_end) FROM STDIN WITH (FORMAT csv)"
        ) as cp:
            cp.write(buf.getvalue())

    active = sum(w["is_active"] for w in wines.values())
    print(f"Loaded {len(wines)} wines ({active} currently listed, {len(featured)} featured) "
          f"and {len(obs)} price observations")


if __name__ == "__main__":
    main()
