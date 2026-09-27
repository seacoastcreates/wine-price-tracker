"""Train a global quantile forecaster for wine list prices and produce forecasts.

Runs locally or as a SageMaker training job (SKLearn framework container). In SageMaker the
input CSV arrives in SM_CHANNEL_TRAIN and everything written to SM_MODEL_DIR is uploaded to S3.

Input CSV columns: wine_id, date, price, promo_price, promo_type, style, tier
(one row per wine per price list; dates are the shared price-list dates, e.g. quarterly).
Outputs: forecasts.csv, metrics.json, model.joblib.

List prices are sticky (in PLCB data ~95% are unchanged quarter to quarter), so the main output
is a price-change model: for each horizon h = 1..H, the probability that the list price will be
higher / lower than today, plus the typical size of a rise or a cut. These are scored against the
historical base rate (Brier skill, ROC AUC, average precision).

Alongside, one gradient-boosted model per quantile (p10/p50/p90) gives a price range, calibrated
with conformalized quantile regression so the 80% interval covers ~80% of outcomes.
All models are global (trained across every wine) and direct multi-horizon, evaluated on a
time-based holdout before being refit on all data.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

QUANTILES = (0.1, 0.5, 0.9)
LAGS = (1, 2, 4, 8)
FEATURES = [*(f"lr_{k}" for k in LAGS), "vol_4", "changes_8", "periods_since_change", "age", "log_price",
            "on_sale", "on_clearance", "discount", "h", "target_period_of_year", "style", "tier"]
CATEGORICAL = ["style", "tier"]
MOVE = np.log(1.005)  # a list-price change smaller than 0.5% counts as "no change"


def build_origins(df: pd.DataFrame, periods: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per (wine, listed period) with features known at that period.

    Series are laid on the shared grid of price-list dates so gaps (a wine missing from a
    list) stay gaps rather than being silently bridged."""
    per_year = max(1, round(len(periods) / ((periods[-1] - periods[0]).days / 365.25 + 1e-9)))
    grid = pd.Series(np.arange(len(periods)), index=periods)
    frames = []
    for wine_id, g in df.groupby("wine_id"):
        g = g.set_index("date").reindex(periods)
        listed = g["price"].notna()
        logp = np.log(g["price"])
        f = pd.DataFrame(index=periods)
        f["wine_id"] = wine_id
        f["log_price"] = logp
        for k in LAGS:
            f[f"lr_{k}"] = logp - logp.shift(k)
        diffs = logp.diff()
        f["vol_4"] = diffs.rolling(4, min_periods=2).std()
        f["changes_8"] = (diffs.abs() > 1e-9).astype(float).where(diffs.notna()).rolling(8, min_periods=1).sum()
        changed = (diffs.abs() > 1e-9).to_numpy()
        since, last = [], None
        for i, c in enumerate(changed):
            if c:
                last = i
            since.append(i - last if last is not None else i - int(np.argmax(listed.to_numpy())))
        f["periods_since_change"] = since
        f["age"] = listed.cumsum()
        f["on_sale"] = (g["promo_type"] == "sale").astype(float)
        f["on_clearance"] = (g["promo_type"] == "clearance").astype(float)
        f["discount"] = (1 - g["promo_price"] / g["price"]).fillna(0.0)
        f["style"] = g["style"].ffill().bfill()
        f["tier"] = g["tier"].ffill().bfill()
        f["t"] = grid.to_numpy()
        frames.append(f[listed].rename_axis("origin").reset_index())
    out = pd.concat(frames, ignore_index=True)
    out["per_year"] = per_year
    for c in CATEGORICAL:
        out[c] = out[c].astype("category")
    return out


def expand_horizons(origins: pd.DataFrame, periods: pd.DatetimeIndex, horizon: int, with_target: bool,
                    future_dates: list[pd.Timestamp] | None = None) -> pd.DataFrame:
    """Cross origins with h = 1..H; attach the target log ratio when it is observable."""
    logp = origins.set_index(["wine_id", "t"])["log_price"]
    per_year = int(origins["per_year"].iloc[0])
    rows = []
    for h in range(1, horizon + 1):
        x = origins.copy()
        x["h"] = h
        x["target_t"] = x["t"] + h
        x["target_period_of_year"] = x["target_t"] % per_year
        if with_target:
            idx = pd.MultiIndex.from_arrays([x["wine_id"], x["target_t"]])
            x["y"] = logp.reindex(idx).to_numpy() - x["log_price"].to_numpy()
            x = x.dropna(subset=["y"])
            x["target_date"] = periods[x["target_t"].to_numpy()]
        else:
            x["target_date"] = future_dates[h - 1]
        rows.append(x)
    return pd.concat(rows, ignore_index=True)


def fit_models(train: pd.DataFrame, seed: int) -> dict:
    cat_mask = [c in CATEGORICAL for c in FEATURES]
    models = {}
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.05,
                                          max_leaf_nodes=31, min_samples_leaf=50, l2_regularization=1.0,
                                          categorical_features=cat_mask, random_state=seed)
        models[q] = m.fit(train[FEATURES], train["y"])
    return models


def fit_conformal(samples: pd.DataFrame, cutoff_t: int, calib_periods: int, seed: int) -> dict:
    """Conformalized quantile regression: fit on data before a calibration window, then widen
    (or narrow) the p10/p90 band per horizon so it covers ~80% of calibration outcomes."""
    calib_start = cutoff_t - calib_periods
    fit = samples[samples["target_t"] <= calib_start]
    calib = samples[(samples["target_t"] > calib_start) & (samples["target_t"] <= cutoff_t)]
    models = fit_models(fit, seed)
    raw = raw_predict(models, calib)
    y = calib["y"].to_numpy()
    scores = np.maximum(raw[:, 0] - y, y - raw[:, 2])
    target = QUANTILES[-1] - QUANTILES[0]
    adjust = {}
    for h, idx in calib.groupby("h").indices.items():
        n = len(idx)
        adjust[int(h)] = float(np.quantile(scores[idx], min(1.0, np.ceil((n + 1) * target) / n)))
    return {"models": models, "adjust": adjust}


def direction_of(y: pd.Series) -> np.ndarray:
    return np.where(y > MOVE, 2, np.where(y < -MOVE, 0, 1))


def fit_change_models(samples: pd.DataFrame, cutoff_t: int, calib_periods: int, seed: int) -> dict:
    """P(up), P(down) at each horizon, and the median size of an up / down move.

    The classifier is fit on data before a recent calibration window, then its probabilities are
    recalibrated per horizon with Platt scaling on that window (monotone, so ranking is kept),
    so they reflect the current
    rate of price changes rather than the full history (which includes one-off shocks)."""
    calib_start = cutoff_t - calib_periods
    train = samples[samples["target_t"] <= calib_start]
    calib = samples[(samples["target_t"] > calib_start) & (samples["target_t"] <= cutoff_t)]
    cat_mask = [c in CATEGORICAL for c in FEATURES]
    direction = direction_of(train["y"])
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=100,
                                         l2_regularization=1.0, categorical_features=cat_mask, random_state=seed)
    clf.fit(train[FEATURES], direction)
    size = {}
    for name, mask in (("up", direction == 2), ("down", direction == 0)):
        reg = HistGradientBoostingRegressor(loss="quantile", quantile=0.5, max_iter=200, learning_rate=0.05,
                                            min_samples_leaf=50, categorical_features=cat_mask, random_state=seed)
        size[name] = reg.fit(train.loc[mask, FEATURES], train.loc[mask, "y"])
    # Base rates from the calibration window: the "no model" forecast the model must beat.
    base_rate = {int(h): {"up": float(np.mean(g["y"] > MOVE)), "down": float(np.mean(g["y"] < -MOVE))}
                 for h, g in calib.groupby("h")}
    change = {"clf": clf, "size": size, "base_rate": base_rate, "calibrators": {}}
    raw = raw_change_proba(change, calib)
    for h, idx in calib.groupby("h").indices.items():
        d = direction_of(calib["y"].iloc[idx])
        change["calibrators"][int(h)] = {
            side: LogisticRegression().fit(logit(raw[side][idx]), d == cls)
            for side, cls in (("up", 2), ("down", 0))
        }
    return change


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def raw_change_proba(change: dict, x: pd.DataFrame) -> dict:
    proba = change["clf"].predict_proba(x[FEATURES])
    classes = list(change["clf"].classes_)
    return {"up": proba[:, classes.index(2)], "down": proba[:, classes.index(0)]}


def predict_change(change: dict, x: pd.DataFrame) -> pd.DataFrame:
    raw = raw_change_proba(change, x)
    p = {"up": np.empty(len(x)), "down": np.empty(len(x))}
    h = x["h"].to_numpy()
    for hh, cal in change["calibrators"].items():
        m = h == hh
        for side in p:
            if m.any():
                p[side][m] = cal[side].predict_proba(logit(raw[side][m]))[:, 1]
    return pd.DataFrame({
        "p_up": p["up"],
        "p_down": p["down"],
        "up_pct": np.expm1(np.maximum(change["size"]["up"].predict(x[FEATURES]), MOVE)) * 100,
        "down_pct": np.expm1(np.minimum(change["size"]["down"].predict(x[FEATURES]), -MOVE)) * 100,
    }, index=x.index)


def evaluate_change(change: dict, test: pd.DataFrame) -> dict:
    pred = predict_change(change, test)
    out = {}
    for h, idx in test.groupby("h").indices.items():
        g, pr = test.iloc[idx], pred.iloc[idx]
        base = change["base_rate"][int(h)]
        row = {}
        for side, actual in (("up", g["y"] > MOVE), ("down", g["y"] < -MOVE)):
            y, p = actual.to_numpy(), pr[f"p_{side}"].to_numpy()
            brier, brier_base = brier_score_loss(y, p), brier_score_loss(y, np.full_like(p, base[side]))
            row[side] = {
                "actual_rate_pct": round(float(y.mean() * 100), 2),
                "predicted_rate_pct": round(float(p.mean() * 100), 2),
                "roc_auc": round(float(roc_auc_score(y, p)), 3) if 0 < y.sum() < len(y) else None,
                "avg_precision": round(float(average_precision_score(y, p)), 3) if y.sum() else None,
                "brier_skill_vs_base_rate": round(float(1 - brier / brier_base), 3),
            }
        out[int(h)] = row
    return out


def raw_predict(models: dict, x: pd.DataFrame) -> np.ndarray:
    return np.column_stack([models[q].predict(x[FEATURES]) for q in QUANTILES])


def predict(bundle: dict, x: pd.DataFrame) -> np.ndarray:
    """Returns an (n, 3) array of log ratios with conformal band adjustment, never crossing."""
    preds = raw_predict(bundle["models"], x)
    adj = x["h"].map(bundle["adjust"]).fillna(max(bundle["adjust"].values())).to_numpy()
    preds[:, 0] -= adj
    preds[:, 2] += adj
    return np.sort(preds, axis=1)


def price_mape(y, yhat) -> float:
    """MAPE on prices, computed from log ratios relative to the same origin price."""
    actual, pred = np.exp(y), np.exp(yhat)
    return float(np.mean(np.abs(pred - actual) / actual) * 100)


def pinball(y, yhat, q) -> float:
    d = y - yhat
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def evaluate(bundle: dict, test: pd.DataFrame) -> dict:
    preds = predict(bundle, test)
    y = test["y"].to_numpy()
    zero = np.zeros_like(y)
    # Drift baseline: each wine's own average change per period so far, extrapolated.
    drift = (test["lr_4"].fillna(0) / 4 * test["h"]).to_numpy()
    changed = np.abs(y) > 1e-9
    by_h = {}
    for h, idx in test.groupby("h").indices.items():
        by_h[int(h)] = {
            "model_mape": round(price_mape(y[idx], preds[idx, 1]), 2),
            "naive_mape": round(price_mape(y[idx], zero[idx]), 2),
            "coverage_80": round(float(np.mean((y[idx] >= preds[idx, 0]) & (y[idx] <= preds[idx, 2])) * 100), 1),
        }
    return {
        "holdout_rows": int(len(test)),
        "share_price_changed_pct": round(float(changed.mean() * 100), 1),
        "mape": {
            "model_p50": round(price_mape(y, preds[:, 1]), 2),
            "naive_last_price": round(price_mape(y, zero), 2),
            "drift": round(price_mape(y, drift), 2),
        },
        "mape_when_price_changed": {
            "model_p50": round(price_mape(y[changed], preds[changed, 1]), 2),
            "naive_last_price": round(price_mape(y[changed], zero[changed]), 2),
        },
        "interval_80_coverage_pct": round(float(np.mean((y >= preds[:, 0]) & (y <= preds[:, 2])) * 100), 1),
        "pinball": {str(q): round(pinball(y, preds[:, i], q), 5) for i, q in enumerate(QUANTILES)},
        "by_horizon": by_h,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=4)
    ap.add_argument("--holdout-periods", type=int, default=4)
    ap.add_argument("--calib-periods", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--input", default=os.environ.get("SM_CHANNEL_TRAIN", "data"))
    ap.add_argument("--output", default=os.environ.get("SM_MODEL_DIR", "artifacts"))
    args = ap.parse_args()

    in_path = Path(args.input)
    csv = in_path if in_path.is_file() else next(in_path.glob("*.csv"))
    df = pd.read_csv(csv, parse_dates=["date"])
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    periods = pd.DatetimeIndex(sorted(df["date"].unique()))
    last_t = len(periods) - 1
    origins = build_origins(df, periods)
    samples = expand_horizons(origins, periods, args.horizon, with_target=True)

    # Time-based holdout: fit and calibrate only on targets observed before the cutoff,
    # so nothing from the evaluation window leaks in.
    cutoff_t = last_t - args.holdout_periods
    test = samples[samples["target_t"] > cutoff_t]
    metrics = evaluate(fit_conformal(samples, cutoff_t, args.calib_periods, args.seed), test)
    metrics["price_change"] = evaluate_change(fit_change_models(samples, cutoff_t, args.calib_periods, args.seed), test)
    print(json.dumps({k: v for k, v in metrics.items() if k != "by_horizon"}, indent=2))

    # Refit using all data (the most recent periods become the calibration window), then
    # forecast forward from the latest price list for wines that are still listed.
    bundle = fit_conformal(samples, last_t, args.calib_periods, args.seed)
    change = fit_change_models(samples, last_t, args.calib_periods, args.seed)
    months = round((periods[-1] - periods[-2]).days / 30.44)
    future_dates = [periods[-1] + pd.DateOffset(months=months * h) for h in range(1, args.horizon + 1)]
    latest = origins[origins["t"] == last_t]
    future = expand_horizons(latest, periods, args.horizon, with_target=False, future_dates=future_dates)
    preds = predict(bundle, future)
    chg = predict_change(change, future)
    forecasts = pd.DataFrame({
        "wine_id": future["wine_id"],
        "target_date": pd.to_datetime(future["target_date"]).dt.date,
        **{f"p{int(q * 100)}": np.round(np.exp(future["log_price"].to_numpy() + preds[:, i]), 2)
           for i, q in enumerate(QUANTILES)},
        "p_up": chg["p_up"].round(4),
        "p_down": chg["p_down"].round(4),
        "up_pct": chg["up_pct"].round(1),
        "down_pct": chg["down_pct"].round(1),
    })

    model_version = dt.datetime.now(dt.timezone.utc).strftime("hgbq-%Y%m%d-%H%M%S")
    forecasts.to_csv(out / "forecasts.csv", index=False)
    (out / "metrics.json").write_text(json.dumps({
        "model_version": model_version,
        "algorithm": "Gradient-boosted price-change classifier + conformal quantile range (global, direct multi-horizon)",
        "horizon": args.horizon,
        "horizon_unit": "quarter",
        "trained_on_rows": int(len(samples)),
        "series": int(df["wine_id"].nunique()),
        "data_through": str(periods[-1].date()),
        **metrics,
    }, indent=2))
    joblib.dump({**bundle, "change": change, "features": FEATURES, "quantiles": QUANTILES}, out / "model.joblib")
    print(f"Wrote {len(forecasts)} forecast rows for model {model_version} to {out}")


if __name__ == "__main__":
    main()
