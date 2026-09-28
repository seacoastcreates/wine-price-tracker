"""Next-vintage pricing: when a new vintage of a wine arrives, how is it priced vs the previous one?

New vintages are where growing conditions and harvest size show up in prices (a small or
acclaimed vintage is released higher), and they move far more often than shelf prices: in the
PLCB data ~42% of new vintages arrive priced above the previous vintage, ~16% below.

One row per transition (family, previous vintage -> new vintage), observed on the first price list
that carries the new vintage. Target: log(new list price / previous vintage's latest list price).
Every feature is known on that date.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, roc_auc_score

from wineprice.features import SUPPLY_LAG_MONTHS, WEATHER_VARS, Context, _latest_harvest_vintage
from wineprice.windows import drinking_window

MOVE = np.log(1.005)
MAX_CURRENT_AGE = 8  # only forecast a next vintage for current vintages at most this many years old
BASE = ["prev_log_price", "vintage_gap", "prev_life_quarters", "prev_life_change", "prev_changes",
        "prev_on_sale", "prev_on_clearance", "family_prev_transitions", "family_mean_change",
        "market_up_share_4q", "style", "tier"]
GROUPS = {
    "weather": [f"new_{v}" for v in WEATHER_VARS] + [f"diff_{v}" for v in WEATHER_VARS],
    "supply": ["new_tons_yoy", "new_grape_price_yoy"],
    "window": ["window_start", "window_end"],
    # The producer's recent behavior: its other wines' list-price rises and new-vintage repricing.
    "brand": ["brand_n_listed", "brand_up_share_4q", "brand_recent_vintage_change", "brand_recent_vintage_n"],
    "attributes": ["grape", "classification"],
}
CATEGORICAL = ["style", "tier", "grape", "classification"]
BRAND_LOOKBACK_MONTHS = 24


def vintage_features(names: tuple[str, ...]) -> list[str]:
    return BASE + [f for g in names for f in GROUPS[g]]


def market_up_share(df: pd.DataFrame) -> pd.Series:
    """Share of listed wines whose list price rose over the previous 4 price lists, per date: a
    market-wide inflation signal (e.g. the statewide increase in April 2023)."""
    p = df.pivot_table(index="date", columns="wine_id", values="price")
    rose = (np.log(p).diff() > MOVE).astype(float).where(p.notna() & p.shift(1).notna())
    listed = (p.notna() & p.shift(1).notna()).astype(float)
    return (rose.sum(axis=1).rolling(4, min_periods=1).sum()
            / listed.sum(axis=1).rolling(4, min_periods=1).sum()).rename("market_up_share_4q")


def build_transitions(df: pd.DataFrame, context: Context | None = None) -> pd.DataFrame:
    """One row per vintage transition within each family, with features and (if known) target."""
    ctx = context or Context()
    df = df[pd.to_numeric(df["vintage"], errors="coerce").notna()].copy()
    df["vint"] = df["vintage"].astype(int)
    market = market_up_share(df)
    wines = (df.sort_values("date").groupby("wine_id")
             .agg(family=("family", "first"), vint=("vint", "first"), region=("region", "first"),
                  brand=("brand", "first"), grape=("grape", "first"), classification=("classification", "first"),
                  style=("style", "last"), tier=("tier", "last"), first_seen=("date", "min"),
                  last_seen=("date", "max")))
    by_wine = {w: g.sort_values("date") for w, g in df.groupby("wine_id")}

    rows = []
    for family, fam in wines.sort_values("vint").groupby("family"):
        fam = fam.sort_values("vint")
        history: list[float] = []
        for (_, prev), (new_id, new) in zip(fam.iloc[:-1].iterrows(), fam.iloc[1:].iterrows()):
            t0 = new["first_seen"]
            prev_hist = by_wine[prev.name]
            prev_hist = prev_hist[prev_hist["date"] <= t0]
            if prev_hist.empty:
                continue
            last = prev_hist.iloc[-1]
            new_price = by_wine[new_id].iloc[0]["price"]
            logp = np.log(prev_hist["price"].to_numpy())
            rows.append({
                "family": family, "wine_id": new_id, "prev_wine_id": prev.name, "date": t0,
                "new_vintage": new["vint"], "prev_vintage": prev["vint"], "region": new["region"],
                "brand": new["brand"], "grape": new["grape"], "classification": new["classification"],
                "style": new["style"], "tier": new["tier"],
                "prev_price": last["price"], "prev_log_price": float(np.log(last["price"])),
                "vintage_gap": new["vint"] - prev["vint"],
                "prev_life_quarters": len(prev_hist),
                "prev_life_change": float(logp[-1] - logp[0]),
                "prev_changes": int((np.abs(np.diff(logp)) > MOVE).sum()),
                "prev_on_sale": float(last["promo_type"] == "sale"),
                "prev_on_clearance": float(last["promo_type"] == "clearance"),
                "family_prev_transitions": len(history),
                "family_mean_change": float(np.mean(history)) if history else np.nan,
                "market_up_share_4q": float(market.get(t0, np.nan)),
                "y": float(np.log(new_price / last["price"])),
            })
            history.append(rows[-1]["y"])
    t = pd.DataFrame(rows)
    # On the first price list every vintage is "new"; those aren't real releases.
    t = t[t["date"] > df["date"].min()].reset_index(drop=True)
    add_brand_history(t, t)
    add_vintage_context(t, ctx)
    for c in CATEGORICAL:
        t[c] = t[c].astype("category")
    return t


def add_brand_history(t: pd.DataFrame, history: pd.DataFrame) -> None:
    """Mean price change of the brand's *other* families' new vintages released in the prior 24
    months (strictly before each row's date), from the `history` transitions."""
    means, counts = [], []
    by_brand = {b: g for b, g in history.groupby("brand")}
    for _, r in t.iterrows():
        g = by_brand.get(r["brand"])
        if g is None:
            means.append(np.nan)
            counts.append(0)
            continue
        m = g[(g["family"] != r["family"]) & (g["date"] < r["date"])
              & (g["date"] >= r["date"] - pd.DateOffset(months=BRAND_LOOKBACK_MONTHS))]
        means.append(float(m["y"].mean()) if len(m) else np.nan)
        counts.append(len(m))
    t["brand_recent_vintage_change"] = means
    t["brand_recent_vintage_n"] = counts


def add_vintage_context(t: pd.DataFrame, ctx: Context) -> None:
    region, new_v, prev_v = t["region"], t["new_vintage"], t["prev_vintage"]
    last_done = _latest_harvest_vintage(pd.to_datetime(t["date"]), region.map(ctx.hemispheres))
    if ctx.weather is not None:
        w = ctx.weather.set_index(["region", "vintage"])[WEATHER_VARS]
        new = w.reindex(pd.MultiIndex.from_arrays([region, new_v])).to_numpy()
        prev = w.reindex(pd.MultiIndex.from_arrays([region, prev_v])).to_numpy()
        new[(new_v > last_done).to_numpy()] = np.nan
        for i, v in enumerate(WEATHER_VARS):
            t[f"new_{v}"] = new[:, i]
            t[f"diff_{v}"] = new[:, i] - prev[:, i]
    else:
        for v in WEATHER_VARS:
            t[f"new_{v}"] = t[f"diff_{v}"] = np.nan
    published = (pd.to_datetime(t["date"]) - pd.DateOffset(months=SUPPLY_LAG_MONTHS)).dt.year
    if ctx.supply is not None:
        s = ctx.supply.set_index(["region", "crop_year"])[["tons_yoy", "price_yoy"]]
        own = s.reindex(pd.MultiIndex.from_arrays([region, new_v])).to_numpy()
        own[(new_v > published).to_numpy()] = np.nan
        t["new_tons_yoy"], t["new_grape_price_yoy"] = own[:, 0], own[:, 1]
    else:
        t["new_tons_yoy"] = t["new_grape_price_yoy"] = np.nan
    if ctx.brand_stats is not None:
        b = ctx.brand_stats.set_index(["date", "brand"])
        st = b.reindex(pd.MultiIndex.from_arrays([pd.to_datetime(t["date"]), t["brand"]]))
        t["brand_n_listed"] = st["n_listed"].to_numpy()
        t["brand_up_share_4q"] = np.where(st["n_valid_4"] > 0, st["n_up_4"] / st["n_valid_4"].where(st["n_valid_4"] > 0), np.nan)
    else:
        t["brand_n_listed"] = t["brand_up_share_4q"] = np.nan
    win = [drinking_window(r if isinstance(r, str) else None, s, tr)
           for r, s, tr in zip(region, t["style"].astype(str), t["tier"].astype(str))]
    t["window_start"] = [a for a, _ in win]
    t["window_end"] = [b for _, b in win]


def next_vintage_rows(df: pd.DataFrame, transitions: pd.DataFrame, context: Context | None = None) -> pd.DataFrame:
    """Pseudo-transitions for forecasting: for each family, its newest vintage that is on the latest
    price list -> the following vintage, assumed to arrive on the next price list."""
    ctx = context or Context()
    df = df[pd.to_numeric(df["vintage"], errors="coerce").notna()].copy()
    df["vint"] = df["vintage"].astype(int)
    last_date = df["date"].max()
    months = round((last_date - sorted(df["date"].unique())[-2]).days / 30.44)
    as_of = last_date + pd.DateOffset(months=months)
    market = market_up_share(df)
    current = df[df["date"] == last_date].sort_values("vint").groupby("family").tail(1)
    # Old back-vintages (library releases) aren't followed by a "next" vintage; skip them.
    current = current[current["vint"] >= last_date.year - MAX_CURRENT_AGE]
    fam_hist = transitions.groupby("family")["y"].agg(["count", "mean"])
    rows = []
    for _, cur in current.iterrows():
        hist = df[df["wine_id"] == cur["wine_id"]].sort_values("date")
        logp = np.log(hist["price"].to_numpy())
        n, mean = (fam_hist.loc[cur["family"]] if cur["family"] in fam_hist.index else (0, np.nan))
        rows.append({
            "family": cur["family"], "wine_id": cur["wine_id"], "date": as_of,
            "new_vintage": cur["vint"] + 1, "prev_vintage": cur["vint"], "region": cur["region"],
            "brand": cur["brand"], "grape": cur["grape"], "classification": cur["classification"],
            "style": cur["style"], "tier": cur["tier"], "prev_price": cur["price"],
            "prev_log_price": float(np.log(cur["price"])), "vintage_gap": 1,
            "prev_life_quarters": len(hist), "prev_life_change": float(logp[-1] - logp[0]),
            "prev_changes": int((np.abs(np.diff(logp)) > MOVE).sum()),
            "prev_on_sale": float(cur["promo_type"] == "sale"),
            "prev_on_clearance": float(cur["promo_type"] == "clearance"),
            "family_prev_transitions": int(n), "family_mean_change": float(mean),
            "market_up_share_4q": float(market.get(last_date, np.nan)),
        })
    t = pd.DataFrame(rows)
    add_brand_history(t, transitions)
    # Context as of the latest list: the release date is in the future, and brand statistics and
    # published data are only known up to today.
    t_ctx = t.assign(date=last_date)
    add_vintage_context(t_ctx, ctx)
    for c in t_ctx.columns.difference(t.columns):
        t[c] = t_ctx[c]
    for c in CATEGORICAL:
        t[c] = t[c].astype("category")
    return t


@dataclass
class VintageModel:
    """Predicts the price change of a wine's next vintage vs its current one."""

    regressors: dict            # quantile -> fitted model
    classifier: object          # P(down / same / up)
    groups: tuple[str, ...] = ()
    context: Context = field(default_factory=Context)

    @property
    def features(self) -> list[str]:
        return vintage_features(self.groups)

    @classmethod
    def fit(cls, t: pd.DataFrame, groups: tuple[str, ...], seed: int, context: Context | None = None) -> "VintageModel":
        feats = vintage_features(groups)
        mask = [c in CATEGORICAL for c in feats]
        regs = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.05,
                                                 min_samples_leaf=30, l2_regularization=1.0,
                                                 categorical_features=mask, random_state=seed).fit(t[feats], t["y"])
                for q in (0.1, 0.5, 0.9)}
        direction = np.where(t["y"] > MOVE, 2, np.where(t["y"] < -MOVE, 0, 1))
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, min_samples_leaf=30,
                                             l2_regularization=1.0, categorical_features=mask,
                                             random_state=seed).fit(t[feats], direction)
        from dataclasses import replace
        return cls(regs, clf, tuple(groups), replace(context or Context(), brand_stats=None))

    def predict(self, t: pd.DataFrame) -> pd.DataFrame:
        q = np.sort(np.column_stack([self.regressors[k].predict(t[self.features]) for k in (0.1, 0.5, 0.9)]), axis=1)
        proba = self.classifier.predict_proba(t[self.features])
        classes = list(self.classifier.classes_)
        return pd.DataFrame({"p10": q[:, 0], "p50": q[:, 1], "p90": q[:, 2],
                             "p_up": proba[:, classes.index(2)], "p_down": proba[:, classes.index(0)]},
                            index=t.index)


def evaluate_vintage(model: VintageModel, test: pd.DataFrame) -> dict:
    pred = model.predict(test)
    y = test["y"].to_numpy()
    up = y > MOVE
    fam = test["family_mean_change"].fillna(0).to_numpy()
    return {
        "transitions": int(len(test)),
        "share_up_pct": round(float(up.mean() * 100), 1),
        "mae_log": {
            "model_p50": round(float(mean_absolute_error(y, pred["p50"])), 4),
            "same_price": round(float(mean_absolute_error(y, np.zeros_like(y))), 4),
            "family_history": round(float(mean_absolute_error(y, fam)), 4),
        },
        "rise_roc_auc": round(float(roc_auc_score(up, pred["p_up"])), 4) if 0 < up.sum() < len(up) else None,
        "interval_80_coverage_pct": round(float(np.mean((y >= pred["p10"]) & (y <= pred["p90"])) * 100), 1),
    }
