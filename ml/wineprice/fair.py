"""Fair-price (hedonic) model: what should this wine cost, given what it is?

Predicts the log list price of a wine from its attributes (region, grape, classification, style,
bottle size, age of the vintage, listing year), its name (words like "Reserve" or a vineyard name
carry price information), and its producer's price level from the producer's *other* wines. It
never sees the wine's own price. The gap between shelf price and fair price is a value signal.

Leakage rules:
- one row per wine, at its most recent listing; price tier is excluded (it is derived from price);
- cross-validation is grouped by family (all vintages of a wine), so a wine is priced by a model
  that saw none of its vintages;
- the producer encoding and the name-text score are fitted on training folds only, and the text
  score fed to the tree model is itself out-of-fold.
"""

import re

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold

from wineprice.features import WEATHER_VARS, Context

CATEGORICAL = ["style", "region", "grape", "classification", "size"]
NUMERIC = ["vintage_age", "is_nv", "listing_year", "brand_mean_logp", "brand_n_families", "brand_std_logp"]
TEXT = ["name_score"]
GROUPS = {"weather": [f"vint_{v}" for v in WEATHER_VARS]}
QUANTILES = (0.1, 0.5, 0.9)


def feature_list(use_text: bool = True, use_brand: bool = True, groups: tuple[str, ...] = ()) -> list[str]:
    num = [f for f in NUMERIC if use_brand or not f.startswith("brand_")]
    return CATEGORICAL + num + (TEXT if use_text else []) + [f for g in groups for f in GROUPS[g]]


def name_text(name: str) -> str:
    """Name without vintage years, lower case (the vintage enters as a separate feature)."""
    return re.sub(r"\b(19|20)\d{2}\b", " ", str(name).lower())


def latest_rows(df: pd.DataFrame, context: Context | None = None) -> pd.DataFrame:
    """One row per wine: its most recent listing, with attribute features."""
    last = df.sort_values("date").groupby("wine_id").tail(1).copy()
    vint = pd.to_numeric(last["vintage"], errors="coerce")
    last["vintage_age"] = last["date"].dt.year - vint
    last["is_nv"] = vint.isna().astype(float)
    last["listing_year"] = last["date"].dt.year + (last["date"].dt.month - 1) / 12
    last["y"] = np.log(last["price"])
    last["text"] = last["name"].map(name_text)
    ctx = context or Context()
    if ctx.weather is not None:
        w = ctx.weather.set_index(["region", "vintage"])[WEATHER_VARS]
        vals = w.reindex(pd.MultiIndex.from_arrays([last["region"], vint])).to_numpy()
        for i, v in enumerate(WEATHER_VARS):
            last[f"vint_{v}"] = vals[:, i]
    else:
        for v in WEATHER_VARS:
            last[f"vint_{v}"] = np.nan
    for c in CATEGORICAL:
        last[c] = last[c].astype("category")
    return last.reset_index(drop=True)


def brand_encoding(train: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Producer price level for each target row from training rows of *other* families of the
    same brand (so a wine's own vintages never inform its producer's level)."""
    fam = train.groupby(["brand", "family"], observed=True)["y"].agg(["sum", "count"]).reset_index()
    fam_mean = fam.assign(mean=fam["sum"] / fam["count"])
    by_brand = fam_mean.groupby("brand")
    tot = by_brand["sum"].sum()
    cnt = by_brand["count"].sum()
    nfam = by_brand["family"].nunique()
    sq = train.assign(y2=train["y"] ** 2).groupby("brand")["y2"].sum()
    own = fam.set_index(["brand", "family"])
    b, f = target["brand"], target["family"]
    key = pd.MultiIndex.from_arrays([b, f])
    own_sum = own["sum"].reindex(key).fillna(0).to_numpy()
    own_cnt = own["count"].reindex(key).fillna(0).to_numpy()
    own_sq = train.assign(y2=train["y"] ** 2).groupby(["brand", "family"])["y2"].sum().reindex(key).fillna(0).to_numpy()
    s = tot.reindex(b).fillna(0).to_numpy() - own_sum
    n = cnt.reindex(b).fillna(0).to_numpy() - own_cnt
    q = sq.reindex(b).fillna(0).to_numpy() - own_sq
    mean = np.where(n > 0, s / np.where(n > 0, n, 1), np.nan)
    var = np.where(n > 1, q / np.where(n > 1, n, 1) - mean ** 2, np.nan)
    families = nfam.reindex(b).fillna(0).to_numpy() - (own_cnt > 0)
    return pd.DataFrame({"brand_mean_logp": mean, "brand_n_families": families,
                         "brand_std_logp": np.sqrt(np.clip(var, 0, None))}, index=target.index)


def fit_text(train: pd.DataFrame) -> tuple[TfidfVectorizer, Ridge]:
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    X = vec.fit_transform(train["text"])
    return vec, Ridge(alpha=1.0).fit(X, train["y"] - train["y"].mean())


def text_scores(train: pd.DataFrame, target: pd.DataFrame | None, folds: int, seed: int) -> tuple[np.ndarray, np.ndarray | None]:
    """Out-of-fold name scores for `train` (grouped by family) and scores for `target` from a
    model fit on all of `train`."""
    oof = np.zeros(len(train))
    for tr, va in GroupKFold(n_splits=folds).split(train, groups=train["family"]):
        vec, ridge = fit_text(train.iloc[tr])
        oof[va] = ridge.predict(vec.transform(train["text"].iloc[va]))
    tgt = None
    if target is not None:
        vec, ridge = fit_text(train)
        tgt = ridge.predict(vec.transform(target["text"]))
    return oof, tgt


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, feats: list[str], seed: int, inner_folds: int = 4) -> pd.DataFrame:
    """Fit on `train`, return p10/p50/p90 log-price predictions for `test`."""
    train, test = train.copy(), test.copy()
    if "brand_mean_logp" in feats:
        # Training rows get a family-excluded encoding from the rest of the training set.
        train[["brand_mean_logp", "brand_n_families", "brand_std_logp"]] = brand_encoding(train, train)
        test[["brand_mean_logp", "brand_n_families", "brand_std_logp"]] = brand_encoding(train, test)
    if "name_score" in feats:
        oof, tgt = text_scores(train, test, inner_folds, seed)
        train["name_score"], test["name_score"] = oof, tgt
    mask = [c in CATEGORICAL for c in feats]
    out = {}
    for q in QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=500, learning_rate=0.05,
                                          max_leaf_nodes=63, min_samples_leaf=20, l2_regularization=1.0,
                                          categorical_features=mask, random_state=seed)
        out[f"p{int(q * 100)}"] = m.fit(train[feats], train["y"]).predict(test[feats])
    pred = pd.DataFrame(out, index=test.index)
    return pd.DataFrame(np.sort(pred.to_numpy(), axis=1), index=test.index, columns=pred.columns)


def cross_validate(rows: pd.DataFrame, feats: list[str], folds: int, seed: int) -> pd.DataFrame:
    """Out-of-fold fair-price predictions for every row, grouped by family."""
    preds = []
    for tr, te in GroupKFold(n_splits=folds).split(rows, groups=rows["family"]):
        preds.append(fit_predict(rows.iloc[tr], rows.iloc[te], feats, seed))
    return pd.concat(preds).sort_index()


def evaluate(rows: pd.DataFrame, pred: pd.DataFrame) -> dict:
    y = rows["y"].to_numpy()
    err = pred["p50"].to_numpy() - y
    ss = float(((y - y.mean()) ** 2).sum())
    return {
        "wines": int(len(rows)),
        "median_abs_pct_error": round(float(np.median(np.abs(np.expm1(err))) * 100), 1),
        "mae_log": round(float(np.mean(np.abs(err))), 4),
        "r2_log": round(1 - float((err ** 2).sum()) / ss, 4),
        "interval_80_coverage_pct": round(float(np.mean((y >= pred["p10"]) & (y <= pred["p90"])) * 100), 1),
    }


def baseline_predictions(rows: pd.DataFrame, folds: int) -> dict[str, np.ndarray]:
    """Simple comparators, also out-of-fold by family: the median log price of the same
    region + grape, and of the producer's other wines (falling back to the region + grape median)."""
    rg = np.full(len(rows), np.nan)
    br = np.full(len(rows), np.nan)
    for tr, te in GroupKFold(n_splits=folds).split(rows, groups=rows["family"]):
        train, test = rows.iloc[tr], rows.iloc[te]
        med = train.groupby(["region", "grape"], observed=True)["y"].median()
        key = pd.MultiIndex.from_arrays([test["region"].astype(object), test["grape"].astype(object)])
        rg[te] = med.reindex(key).fillna(train["y"].median()).to_numpy()
        bmed = train.groupby("brand")["y"].median()
        br[te] = test["brand"].map(bmed).fillna(pd.Series(rg[te], index=test.index)).to_numpy()
    return {"region + grape median": rg, "producer's other wines": br}
