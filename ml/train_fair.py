"""Train and evaluate the fair-price model; write out-of-fold fair prices for current wines.

    python train_fair.py            # -> artifacts/fair_metrics.json, artifacts/fair_prices.csv
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from wineprice.fair import (baseline_predictions, cross_validate, evaluate, feature_list, latest_rows)
from wineprice.features import load_context

VARIANTS = {
    "full": dict(use_text=True, use_brand=True, groups=()),
    "no name text": dict(use_text=False, use_brand=True, groups=()),
    "no producer level": dict(use_text=True, use_brand=False, groups=()),
    "+vintage weather": dict(use_text=True, use_brand=True, groups=("weather",)),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data")
    ap.add_argument("--output", default="artifacts")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    d = Path(args.input)
    df = pd.read_csv(d / "series.csv", parse_dates=["date"], dtype={"vintage": str})
    rows = latest_rows(df, load_context(d))
    print(f"{len(rows)} wines, {rows['family'].nunique()} families")

    results, preds = {}, {}
    for name, kw in VARIANTS.items():
        preds[name] = cross_validate(rows, feature_list(**kw), args.folds, args.seed)
        results[name] = evaluate(rows, preds[name])
        print(f"{name:20} {results[name]}", flush=True)
    for name, p in baseline_predictions(rows, args.folds).items():
        results[f"baseline: {name}"] = evaluate(rows, pd.DataFrame({"p10": p, "p50": p, "p90": p}))
        print(f"{'baseline: ' + name:20} {results[f'baseline: ' + name]}")

    # Widen (or narrow) the band around p50 by one factor so the out-of-fold 80% range covers 80%
    # (a single scalar fitted on held-out predictions; the raw quantile models under-cover).
    best = preds["full"].copy()
    y = rows["y"].to_numpy()
    lo, mid, hi = (best[k].to_numpy() for k in ("p10", "p50", "p90"))
    cover = lambda k: np.mean((y >= mid - k * (mid - lo)) & (y <= mid + k * (hi - mid)))  # noqa: E731
    scale = next(k for k in np.arange(1.0, 3.0, 0.01) if cover(k) >= 0.80)
    best["p10"], best["p90"] = mid - scale * (mid - lo), mid + scale * (hi - mid)
    results["full"]["band_scale"] = round(float(scale), 2)
    results["full"]["interval_80_coverage_pct_calibrated"] = round(float(cover(scale)) * 100, 1)
    print(f"band scale {scale:.2f} -> 80% range covers {cover(scale) * 100:.1f}%")

    # Fair prices for wines on the latest price list, from the out-of-fold "full" model.
    latest = rows["date"] == rows["date"].max()
    out = pd.DataFrame({
        "wine_id": rows.loc[latest, "wine_id"],
        **{f"fair_{k}": np.round(np.exp(best.loc[latest, k]), 2) for k in ("p10", "p50", "p90")},
        "value_pct": np.round((np.exp(rows.loc[latest, "y"] - best.loc[latest, "p50"]) - 1) * 100, 1),
    })
    Path(args.output).mkdir(exist_ok=True)
    out.to_csv(Path(args.output) / "fair_prices.csv", index=False)
    (Path(args.output) / "fair_metrics.json").write_text(json.dumps(
        {"folds": args.folds, "grouped_by": "family", "variants": results, "chosen": "full"}, indent=2))
    print(f"fair prices for {len(out)} current wines")


if __name__ == "__main__":
    main()
