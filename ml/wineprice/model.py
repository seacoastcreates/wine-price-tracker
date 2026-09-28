"""Models for wine list-price forecasting, and the single `forecast` path used by batch and online.

List prices are sticky, so the main output is a price-change model: for each horizon h = 1..H, the
probability that the list price will be higher / lower than today, plus the typical size of a rise
or a cut. Alongside, one gradient-boosted model per quantile (p10/p50/p90) gives a price range,
calibrated with conformalized quantile regression. All models are global (trained across every
wine) and direct multi-horizon.
"""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from dataclasses import replace

from wineprice.features import (MOVE, CATEGORICAL, Context, build_origins, expand_horizons, feature_list,
                                future_dates)

QUANTILES = (0.1, 0.5, 0.9)
ALGORITHM = "Gradient-boosted price-change classifier + conformal quantile range (global, direct multi-horizon)"


# ---- price range: conformalized quantile regression -------------------------------------------

def fit_quantiles(train: pd.DataFrame, seed: int, features: list[str]) -> dict:
    cat_mask = [c in CATEGORICAL for c in features]
    models = {}
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.05,
                                          max_leaf_nodes=31, min_samples_leaf=50, l2_regularization=1.0,
                                          categorical_features=cat_mask, random_state=seed)
        models[q] = m.fit(train[features], train["y"])
    return models


def fit_conformal(samples: pd.DataFrame, cutoff_t: int, calib_periods: int, seed: int,
                  features: list[str]) -> dict:
    """Fit on data before a calibration window, then widen (or narrow) the p10/p90 band per
    horizon so it covers ~80% of calibration outcomes."""
    calib_start = cutoff_t - calib_periods
    fit = samples[samples["target_t"] <= calib_start]
    calib = samples[(samples["target_t"] > calib_start) & (samples["target_t"] <= cutoff_t)]
    models = fit_quantiles(fit, seed, features)
    raw = raw_predict(models, calib, features)
    y = calib["y"].to_numpy()
    scores = np.maximum(raw[:, 0] - y, y - raw[:, 2])
    target = QUANTILES[-1] - QUANTILES[0]
    adjust = {}
    for h, idx in calib.groupby("h").indices.items():
        n = len(idx)
        adjust[int(h)] = float(np.quantile(scores[idx], min(1.0, np.ceil((n + 1) * target) / n)))
    return {"models": models, "adjust": adjust, "features": features}


def raw_predict(models: dict, x: pd.DataFrame, features: list[str]) -> np.ndarray:
    return np.column_stack([models[q].predict(x[features]) for q in QUANTILES])


def predict_range(bundle: dict, x: pd.DataFrame) -> np.ndarray:
    """Returns an (n, 3) array of log ratios with conformal band adjustment, never crossing."""
    preds = raw_predict(bundle["models"], x, bundle["features"])
    adj = x["h"].map(bundle["adjust"]).fillna(max(bundle["adjust"].values())).to_numpy()
    preds[:, 0] -= adj
    preds[:, 2] += adj
    return np.sort(preds, axis=1)


# ---- price change: calibrated classifier + move size -----------------------------------------

def direction_of(y: pd.Series) -> np.ndarray:
    return np.where(y > MOVE, 2, np.where(y < -MOVE, 0, 1))


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def fit_change_models(samples: pd.DataFrame, cutoff_t: int, calib_periods: int, seed: int,
                      features: list[str]) -> dict:
    """P(up), P(down) at each horizon, and the median size of an up / down move.

    The classifier is fit on data before a recent calibration window, then its probabilities are
    recalibrated per horizon with Platt scaling on that window (monotone, so ranking is kept), so
    they reflect the current rate of price changes rather than the full history (which includes
    one-off shocks)."""
    calib_start = cutoff_t - calib_periods
    train = samples[samples["target_t"] <= calib_start]
    calib = samples[(samples["target_t"] > calib_start) & (samples["target_t"] <= cutoff_t)]
    cat_mask = [c in CATEGORICAL for c in features]
    direction = direction_of(train["y"])
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=100,
                                         l2_regularization=1.0, categorical_features=cat_mask, random_state=seed)
    clf.fit(train[features], direction)
    size = {}
    for name, mask in (("up", direction == 2), ("down", direction == 0)):
        reg = HistGradientBoostingRegressor(loss="quantile", quantile=0.5, max_iter=200, learning_rate=0.05,
                                            min_samples_leaf=50, categorical_features=cat_mask, random_state=seed)
        size[name] = reg.fit(train.loc[mask, features], train.loc[mask, "y"])
    # Base rates from the calibration window: the "no model" forecast the model must beat.
    base_rate = {int(h): {"up": float(np.mean(g["y"] > MOVE)), "down": float(np.mean(g["y"] < -MOVE))}
                 for h, g in calib.groupby("h")}
    change = {"clf": clf, "size": size, "base_rate": base_rate, "calibrators": {}, "features": features}
    raw = raw_change_proba(change, calib)
    for h, idx in calib.groupby("h").indices.items():
        d = direction_of(calib["y"].iloc[idx])
        change["calibrators"][int(h)] = {
            side: LogisticRegression().fit(logit(raw[side][idx]), d == cls)
            for side, cls in (("up", 2), ("down", 0))
        }
    return change


def raw_change_proba(change: dict, x: pd.DataFrame) -> dict:
    proba = change["clf"].predict_proba(x[change["features"]])
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
        "up_pct": np.expm1(np.maximum(change["size"]["up"].predict(x[change["features"]]), MOVE)) * 100,
        "down_pct": np.expm1(np.minimum(change["size"]["down"].predict(x[change["features"]]), -MOVE)) * 100,
    }, index=x.index)


# ---- the trained artifact --------------------------------------------------------------------

def serving_context(ctx: Context) -> Context:
    """Serving only forecasts from the latest price list, so the artifact keeps just that date's
    brand statistics (the full table is ~100x larger)."""
    if ctx.brand_stats is None:
        return ctx
    latest = ctx.brand_stats["date"].max()
    return replace(ctx, brand_stats=ctx.brand_stats[ctx.brand_stats["date"] == latest].reset_index(drop=True))


@dataclass
class WinePriceModel:
    """Everything needed to forecast: the fitted models plus metadata. Saved as one joblib file."""

    range_models: dict
    change_models: dict
    horizon: int
    version: str = ""
    feature_groups: tuple[str, ...] = ()
    context: Context = field(default_factory=Context)

    @property
    def features(self) -> list[str]:
        return feature_list(self.feature_groups)

    @classmethod
    def fit(cls, samples: pd.DataFrame, cutoff_t: int, calib_periods: int, horizon: int, seed: int,
            feature_groups: tuple[str, ...] = (), context: Context | None = None,
            version: str = "") -> "WinePriceModel":
        features = feature_list(feature_groups)
        return cls(
            range_models=fit_conformal(samples, cutoff_t, calib_periods, seed, features),
            change_models=fit_change_models(samples, cutoff_t, calib_periods, seed, features),
            horizon=horizon,
            version=version,
            feature_groups=tuple(feature_groups),
            context=serving_context(context or Context()),
        )

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path | str) -> "WinePriceModel":
        model = joblib.load(path)
        if not isinstance(model, WinePriceModel):
            raise TypeError(f"{path} is not a WinePriceModel artifact")
        return model

    def predict_rows(self, x: pd.DataFrame) -> pd.DataFrame:
        """Predictions for feature rows (as built by build_origins + expand_horizons)."""
        rng = predict_range(self.range_models, x)
        chg = predict_change(self.change_models, x)
        base = x["log_price"].to_numpy()
        return pd.DataFrame({
            "wine_id": x["wine_id"].to_numpy(),
            "h": x["h"].to_numpy(),
            "target_date": pd.to_datetime(x["target_date"]).dt.date.to_numpy(),
            **{f"p{int(q * 100)}": np.round(np.exp(base + rng[:, i]), 2) for i, q in enumerate(QUANTILES)},
            "p_up": chg["p_up"].round(4).to_numpy(),
            "p_down": chg["p_down"].round(4).to_numpy(),
            "up_pct": chg["up_pct"].round(1).to_numpy(),
            "down_pct": chg["down_pct"].round(1).to_numpy(),
        })

    def forecast(self, history: pd.DataFrame, periods: pd.DatetimeIndex) -> pd.DataFrame:
        """Forecast forward from the latest price list for every wine in `history` that is on it.

        This is the one code path for both the batch job (all wines) and the API (one wine)."""
        origins = build_origins(history, periods, self.context)
        latest = origins[origins["t"] == len(periods) - 1]
        if latest.empty:
            return pd.DataFrame()
        future = expand_horizons(latest, periods, self.horizon, with_target=False,
                                 dates=future_dates(periods, self.horizon))
        return self.predict_rows(future)
