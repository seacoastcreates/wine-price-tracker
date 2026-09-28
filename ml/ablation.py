"""Ablation: does each external feature group improve the price-change model?

Trains the price-change classifier with the same holdout, seed and calibration for each feature
set, then compares ranking skill (ROC AUC), average precision and Brier skill overall and on the
segments the new features target. Writes artifacts/ablation.json.

    python ablation.py [--input data]
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from wineprice.features import brand_stats, build_origins, expand_horizons, feature_list, load_context
from wineprice.model import MOVE, fit_change_models, predict_change

SETS = {
    "current": ("window",),
    "+brand": ("window", "brand"),
    "+attributes": ("window", "attributes"),
    "+both": ("window", "brand", "attributes"),
}
CA_REGIONS = {"Napa Valley", "Sonoma", "Lodi", "California Central Valley", "Paso Robles", "Santa Barbara",
              "Monterey", "Central Coast"}


def scores(y: np.ndarray, p: np.ndarray, base_rate: float) -> dict:
    if not 0 < y.sum() < len(y):
        return {"n": int(len(y)), "positives": int(y.sum())}
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "avg_precision": round(float(average_precision_score(y, p)), 4),
        "brier_skill": round(float(1 - brier_score_loss(y, p) / brier_score_loss(y, np.full_like(p, base_rate))), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data")
    ap.add_argument("--horizon", type=int, default=4)
    ap.add_argument("--holdout-periods", type=int, default=4)
    ap.add_argument("--calib-periods", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    d = Path(args.input)
    df = pd.read_csv(d / "series.csv", parse_dates=["date"], dtype={"vintage": str})
    periods = pd.DatetimeIndex(sorted(df["date"].unique()))
    context = load_context(d)
    context.brand_stats = brand_stats(df, periods)
    samples = expand_horizons(build_origins(df, periods, context), periods, args.horizon, with_target=True)
    cutoff_t = len(periods) - 1 - args.holdout_periods
    test = samples[samples["target_t"] > cutoff_t]

    segments = {
        "all wines": np.ones(len(test), bool),
        "with a region": test["region"].notna().to_numpy(),
        "California": test["region"].isin(CA_REGIONS).to_numpy(),
        "vintage-dated": (test["is_nv"] == 0).to_numpy(),
        "luxury tier": (test["tier"] == "luxury").to_numpy(),
        "brand with 2+ wines": (test["brand_n_others"] >= 1).to_numpy(),
    }
    results = {}
    for name, groups in SETS.items():
        change = fit_change_models(samples, cutoff_t, args.calib_periods, args.seed, feature_list(groups))
        pred = predict_change(change, test)
        results[name] = {}
        for side in ("up", "down"):
            y_all = (test["y"] > MOVE if side == "up" else test["y"] < -MOVE).to_numpy()
            for seg, mask in segments.items():
                for h in (1, args.horizon):
                    m = mask & (test["h"] == h).to_numpy()
                    base = change["base_rate"][h][side]
                    results[name][f"{side} | {seg} | h={h}"] = scores(y_all[m], pred[f"p_{side}"].to_numpy()[m], base)
        print(f"done: {name}", flush=True)

    Path("artifacts").mkdir(exist_ok=True)
    prev = Path("artifacts/ablation.json")
    history = json.loads(prev.read_text()) if prev.exists() else {}
    out = {"external_data": history.get("external_data", history if "base" in history else {}), "brand_attributes": results}
    prev.write_text(json.dumps(out, indent=2))
    keys = list(results[next(iter(SETS))])
    print(f"\n{'ROC AUC':<44}" + "".join(f"{s:>10}" for s in SETS))
    for k in keys:
        print(f"{k:<44}" + "".join(f"{results[s][k].get('roc_auc', float('nan')):>10.4f}" for s in SETS))
    print(f"\n{'Brier skill vs base rate':<44}" + "".join(f"{s:>10}" for s in SETS))
    for k in keys:
        print(f"{k:<44}" + "".join(f"{results[s][k].get('brier_skill', float('nan')):>10.4f}" for s in SETS))


if __name__ == "__main__":
    main()
