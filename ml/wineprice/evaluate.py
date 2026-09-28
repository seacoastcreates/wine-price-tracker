"""Holdout evaluation: price-range accuracy, price-change skill vs the base rate, and
permutation feature importance."""

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from wineprice.model import MOVE, QUANTILES, predict_change, predict_range


def price_mape(y, yhat) -> float:
    """MAPE on prices, computed from log ratios relative to the same origin price."""
    actual, pred = np.exp(y), np.exp(yhat)
    return float(np.mean(np.abs(pred - actual) / actual) * 100)


def pinball(y, yhat, q) -> float:
    d = y - yhat
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def evaluate_range(range_models: dict, test: pd.DataFrame) -> dict:
    preds = predict_range(range_models, test)
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


def feature_importance(change: dict, test: pd.DataFrame, seed: int, max_rows: int = 40_000) -> list[dict]:
    """Permutation importance for the price-rise model: how much ROC AUC drops when a feature's
    values are shuffled across holdout rows. Horizon `h` is excluded (it is a design input)."""
    rng = np.random.default_rng(seed)
    sample = test.sample(min(len(test), max_rows), random_state=seed)
    y = (sample["y"] > MOVE).to_numpy()
    if not 0 < y.sum() < len(y):
        return []
    base = roc_auc_score(y, predict_change(change, sample)["p_up"])
    out = []
    for feat in (f for f in change["features"] if f != "h"):
        shuffled = sample.copy()
        shuffled[feat] = rng.permutation(shuffled[feat].to_numpy())
        if isinstance(sample[feat].dtype, pd.CategoricalDtype):
            shuffled[feat] = pd.Categorical(shuffled[feat], categories=sample[feat].cat.categories)
        auc = roc_auc_score(y, predict_change(change, shuffled)["p_up"])
        out.append({"feature": feat, "auc_drop": round(float(base - auc), 4)})
    return sorted(out, key=lambda r: r["auc_drop"], reverse=True)
