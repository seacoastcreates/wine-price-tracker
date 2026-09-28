"""Train the wine price models, evaluate on a time-based holdout, and write batch forecasts.

Runs locally or as a SageMaker training job (SKLearn framework container, with this directory as
source_dir so the `wineprice` package ships with it). In SageMaker the input CSV arrives in
SM_CHANNEL_TRAIN and everything written to SM_MODEL_DIR is uploaded to S3.

Input CSV columns: wine_id, date, price, promo_price, promo_type, style, tier, vintage, region,
plus optional context tables in the same folder (regions.csv, region_weather.csv, ca_supply.csv).
Outputs: model.joblib (a wineprice.WinePriceModel), forecasts.csv, metrics.json.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

from wineprice.evaluate import evaluate_change, evaluate_range, feature_importance
from wineprice.features import (FEATURE_GROUPS, brand_stats, build_origins, expand_horizons, feature_list,
                                load_context)
from wineprice.model import ALGORITHM, WinePriceModel, fit_change_models, fit_conformal


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=4)
    ap.add_argument("--holdout-periods", type=int, default=4)
    ap.add_argument("--calib-periods", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--feature-groups", default="window",
                    help=f"comma-separated extra feature groups from {sorted(FEATURE_GROUPS)}, or 'none'")
    ap.add_argument("--input", default=os.environ.get("SM_CHANNEL_TRAIN", "data"))
    ap.add_argument("--output", default=os.environ.get("SM_MODEL_DIR", "artifacts"))
    args = ap.parse_args()

    in_path = Path(args.input)
    csv = in_path if in_path.is_file() else in_path / "series.csv"
    df = pd.read_csv(csv, parse_dates=["date"], dtype={"vintage": str})
    context = load_context(csv.parent)
    groups = tuple(g for g in args.feature_groups.split(",") if g and g != "none")
    features = feature_list(groups)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    periods = pd.DatetimeIndex(sorted(df["date"].unique()))
    last_t = len(periods) - 1
    if "brand" in df:
        context.brand_stats = brand_stats(df, periods)
    samples = expand_horizons(build_origins(df, periods, context), periods, args.horizon, with_target=True)

    # Time-based holdout: fit and calibrate only on targets observed before the cutoff,
    # so nothing from the evaluation window leaks in.
    cutoff_t = last_t - args.holdout_periods
    test = samples[samples["target_t"] > cutoff_t]
    change = fit_change_models(samples, cutoff_t, args.calib_periods, args.seed, features)
    metrics = evaluate_range(fit_conformal(samples, cutoff_t, args.calib_periods, args.seed, features), test)
    metrics["price_change"] = evaluate_change(change, test)
    metrics["feature_importance"] = feature_importance(change, test, args.seed)
    print(json.dumps({k: v for k, v in metrics.items() if k != "by_horizon"}, indent=2))

    # Refit using all data (the most recent periods become the calibration window), then
    # forecast forward from the latest price list with the same code path the API uses.
    version = dt.datetime.now(dt.timezone.utc).strftime("hgbq-%Y%m%d-%H%M%S")
    model = WinePriceModel.fit(samples, last_t, args.calib_periods, args.horizon, args.seed,
                               feature_groups=groups, context=context, version=version)
    forecasts = model.forecast(df, periods).drop(columns="h")

    model.save(out / "model.joblib")
    forecasts.to_csv(out / "forecasts.csv", index=False)
    (out / "metrics.json").write_text(json.dumps({
        "model_version": version,
        "algorithm": ALGORITHM,
        "feature_groups": list(groups),
        "horizon": args.horizon,
        "horizon_unit": "quarter",
        "trained_on_rows": int(len(samples)),
        "series": int(df["wine_id"].nunique()),
        "data_through": str(periods[-1].date()),
        **metrics,
    }, indent=2))
    print(f"Wrote {len(forecasts)} forecast rows for model {version} to {out}")


if __name__ == "__main__":
    main()
