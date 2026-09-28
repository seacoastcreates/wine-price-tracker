"""Train and evaluate the next-vintage pricing model.

Feature sets are compared with rolling-origin evaluation: four one-year test windows, each
trained only on earlier transitions, two seeds each (a single split proved too noisy). The final
model is refit on all transitions. Writes artifacts/vintage_metrics.json, vintage_model.joblib and
vintage_outlook.csv (the next-vintage outlook for current vintages).
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from wineprice.features import brand_stats, load_context
from wineprice.vintage import VintageModel, build_transitions, evaluate_vintage, next_vintage_rows

SETS = {
    "current": ("supply",),
    "+brand": ("supply", "brand"),
    "+attributes": ("supply", "attributes"),
    "+both": ("supply", "brand", "attributes"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data")
    ap.add_argument("--output", default="artifacts")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--groups", default="supply", help="feature groups for the final model, or 'auto'")
    args = ap.parse_args()

    d = Path(args.input)
    context = load_context(d)
    series = pd.read_csv(d / "series.csv", parse_dates=["date"], dtype={"vintage": str})
    context.brand_stats = brand_stats(series, pd.DatetimeIndex(sorted(series["date"].unique())))
    t = build_transitions(series, context)

    last = t["date"].max()
    rows = []
    for k in range(args.folds):
        end = last - pd.DateOffset(years=k)
        start = end - pd.DateOffset(years=1)
        train, test = t[t["date"] <= start], t[(t["date"] > start) & (t["date"] <= end)]
        for name, groups in SETS.items():
            for seed in (int(s) for s in args.seeds.split(",")):
                r = evaluate_vintage(VintageModel.fit(train, groups, seed, context), test)
                rows.append({"fold_end": str(end.date()), "set": name, "seed": seed, "n": r["transitions"],
                             "mae": r["mae_log"]["model_p50"], "same_price_mae": r["mae_log"]["same_price"],
                             "auc": r["rise_roc_auc"]})
    cv = pd.DataFrame(rows)
    per_fold = cv.groupby(["fold_end", "set"])[["mae", "auc"]].mean().unstack("set")
    summary = {}
    for name in SETS:
        dm = per_fold["mae"][name] - per_fold["mae"]["current"]
        da = per_fold["auc"][name] - per_fold["auc"]["current"]
        summary[name] = {"mae": round(float(per_fold["mae"][name].mean()), 4),
                         "auc": round(float(per_fold["auc"][name].mean()), 4),
                         "mae_vs_current": round(float(dm.mean()), 4), "folds_mae_better": int((dm < 0).sum()),
                         "auc_vs_current": round(float(da.mean()), 4), "folds_auc_better": int((da > 0).sum())}
        print(f"{name:12} MAE {summary[name]['mae']:.4f} ({summary[name]['mae_vs_current']:+.4f}, "
              f"better in {summary[name]['folds_mae_better']}/{args.folds})  AUC {summary[name]['auc']:.4f} "
              f"({summary[name]['auc_vs_current']:+.4f}, better in {summary[name]['folds_auc_better']}/{args.folds})")
    same_price = cv.groupby("fold_end")["same_price_mae"].first()
    print("same-price MAE by fold:", same_price.round(4).to_dict())

    if args.groups == "auto":
        best = min(summary, key=lambda n: summary[n]["mae"])
        chosen = SETS[best]
    else:
        chosen = tuple(g for g in args.groups.split(",") if g and g != "none")
    model = VintageModel.fit(t, chosen, 42, context)
    out = Path(args.output)
    out.mkdir(exist_ok=True)
    joblib.dump(model, out / "vintage_model.joblib")
    nxt = next_vintage_rows(series, t, context)
    pred = model.predict(nxt)
    pd.DataFrame({
        "wine_id": nxt["wine_id"], "next_vintage": nxt["new_vintage"],
        "p_up": pred["p_up"].round(4), "p_down": pred["p_down"].round(4),
        **{f"{k}_pct": (np.expm1(pred[k]) * 100).round(1) for k in ("p10", "p50", "p90")},
    }).to_csv(out / "vintage_outlook.csv", index=False)
    (out / "vintage_metrics.json").write_text(json.dumps({
        "transitions": int(len(t)), "folds": args.folds, "chosen_groups": list(chosen),
        "same_price_mae_by_fold": same_price.round(4).to_dict(), "rolling_cv": summary}, indent=2))
    print(f"final groups {list(chosen)}; next-vintage outlook for {len(nxt)} current vintages")


if __name__ == "__main__":
    main()
