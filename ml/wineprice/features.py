"""Feature engineering shared by training (batch) and the API (online), so the two can't drift.

Input frame: one row per wine per price list, columns
wine_id, date, price, promo_price, promo_type, style, tier, vintage, region.
A wine is one vintage of one product; vintage is a year or 'NV'.

Optional context tables add external features (see `Context`): growing-season weather per region
and vintage, California crush-report supply per region and crop year, and heuristic drinking
windows. Every context feature is point-in-time: it is only used once it would have been known.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from wineprice.windows import drinking_window

LAGS = (1, 2, 4, 8)
BASE_FEATURES = [*(f"lr_{k}" for k in LAGS), "vol_4", "changes_8", "periods_since_change", "age", "log_price",
                 "on_sale", "on_clearance", "discount", "vintage_age", "is_nv", "h", "target_period_of_year",
                 "style", "tier"]
WEATHER_VARS = ["gdd_anom", "frost_days_anom", "heat_days_anom", "harvest_rain_anom", "gs_rain_anom"]
FEATURE_GROUPS = {
    # Weather of the wine's own vintage, and of the region's most recent completed harvest.
    "weather": [f"vint_{v}" for v in WEATHER_VARS] + [f"last_{v}" for v in WEATHER_VARS],
    # California crush report: the vintage's crop and the latest published crop, vs the prior year.
    "supply": ["vint_tons_yoy", "vint_grape_price_yoy", "last_tons_yoy", "last_grape_price_yoy"],
    # Where the wine sits in its typical drinking window.
    "window": ["years_to_window", "years_past_window", "in_window"],
    # What the producer did to its *other* wines: producers and distributors reprice ranges together.
    "brand": ["brand_n_others", "brand_up_1q", "brand_up_4q", "brand_down_4q", "brand_rel_price"],
    # Grape variety and classification parsed from the name.
    "attributes": ["grape", "classification"],
}
FEATURES = BASE_FEATURES  # default feature set (kept for callers that don't choose)
CATEGORICAL = ["style", "tier", "grape", "classification"]
MOVE = np.log(1.005)  # a list-price change smaller than 0.5% counts as "no change"
SUPPLY_LAG_MONTHS = 16  # crop year Y's final report is out by April 30 of Y+1 -> usable from May 1 of Y+1


def feature_list(groups: list[str] | tuple[str, ...] = ()) -> list[str]:
    return BASE_FEATURES + [f for g in groups for f in FEATURE_GROUPS[g]]


@dataclass
class Context:
    """External lookup tables. Stored inside the model artifact so serving sees exactly what
    training saw."""

    weather: pd.DataFrame | None = None   # region, vintage, <WEATHER_VARS>
    supply: pd.DataFrame | None = None    # region, crop_year, tons_yoy, price_yoy
    hemispheres: dict[str, str] = field(default_factory=dict)  # region -> 'N' / 'S'
    brand_stats: pd.DataFrame | None = None  # brand, date: listed / valid / up / down counts (see brand_stats)


def load_context(data_dir) -> Context:
    """Reads the context tables written next to the training CSV (missing files -> no features)."""
    from pathlib import Path

    d = Path(data_dir)
    read = lambda name: pd.read_csv(d / name) if (d / name).exists() else None  # noqa: E731
    regions = read("regions.csv")
    return Context(
        weather=read("region_weather.csv"),
        supply=read("ca_supply.csv"),
        hemispheres=dict(zip(regions["name"], regions["hemisphere"])) if regions is not None else {},
    )


def brand_stats(df: pd.DataFrame, periods: pd.DatetimeIndex) -> pd.DataFrame:
    """Per brand and price-list date: wines listed, sum of their log prices, and how many changed
    list price vs the previous list (this quarter and over the last 4). Built from all wines, so a
    single wine's features can exclude its own contribution."""
    price = df.pivot_table(index="date", columns="wine_id", values="price").reindex(periods)
    logp = np.log(price)
    d = logp.diff()
    parts = {
        "n_listed": logp.notna(), "sum_logp": logp.fillna(0.0), "n_valid": d.notna(),
        "n_up": d > MOVE, "n_down": d < -MOVE,
    }
    brand = df.groupby("wine_id")["brand"].first().reindex(price.columns)
    frames = {k: v.astype(float).T.groupby(brand.to_numpy()).sum().T for k, v in parts.items()}
    for k in ("n_valid", "n_up", "n_down"):
        frames[f"{k}_4"] = frames[k].rolling(4, min_periods=1).sum()
    long = pd.concat({k: v.stack() for k, v in frames.items()}, axis=1)
    long.index.names = ["date", "brand"]
    return long.reset_index()


def periods_per_year(periods: pd.DatetimeIndex) -> int:
    return max(1, round(len(periods) / ((periods[-1] - periods[0]).days / 365.25 + 1e-9)))


def future_dates(periods: pd.DatetimeIndex, horizon: int) -> list[pd.Timestamp]:
    """The next `horizon` price-list dates, stepping by whole calendar months."""
    months = round((periods[-1] - periods[-2]).days / 30.44)
    return [periods[-1] + pd.DateOffset(months=months * h) for h in range(1, horizon + 1)]


def build_origins(df: pd.DataFrame, periods: pd.DatetimeIndex, context: Context | None = None) -> pd.DataFrame:
    """One row per (wine, listed period) with features known at that period.

    Series are laid on the shared grid of price-list dates so gaps (a wine missing from a
    list) stay gaps rather than being silently bridged."""
    per_year = periods_per_year(periods)
    grid = pd.Series(np.arange(len(periods)), index=periods)
    frames = []
    first = df.groupby("wine_id").first()
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
        # This wine's own list-price moves, so brand features can exclude them.
        f["own_valid"] = diffs.notna().astype(float)
        f["own_up"] = (diffs > MOVE).astype(float)
        f["own_down"] = (diffs < -MOVE).astype(float)
        for k in ("valid", "up", "down"):
            f[f"own_{k}_4"] = f[f"own_{k}"].rolling(4, min_periods=1).sum()
        f["on_sale"] = (g["promo_type"] == "sale").astype(float)
        f["on_clearance"] = (g["promo_type"] == "clearance").astype(float)
        f["discount"] = (1 - g["promo_price"] / g["price"]).fillna(0.0)
        # Years since the vintage: older vintages get marked up as they age, or cleared out.
        vintage = pd.to_numeric(first.at[wine_id, "vintage"] if "vintage" in first else None, errors="coerce")
        f["vintage_age"] = periods.year - vintage if pd.notna(vintage) else np.nan
        f["is_nv"] = float(pd.isna(vintage))
        f["vintage_year"] = vintage
        for col in ("region", "brand", "grape", "classification"):
            f[col] = first.at[wine_id, col] if col in first else None
        f["style"] = g["style"].ffill().bfill()
        f["tier"] = g["tier"].ffill().bfill()
        f["t"] = grid.to_numpy()
        frames.append(f[listed].rename_axis("origin").reset_index())
    out = pd.concat(frames, ignore_index=True)
    out["per_year"] = per_year
    add_context_features(out, context or Context())
    for c in CATEGORICAL:
        out[c] = out[c].astype("category")
    return out


def _latest_harvest_vintage(origin: pd.Series, hemisphere: pd.Series) -> pd.Series:
    """The most recent vintage whose growing season had finished by `origin` (season ends Oct 31
    in the north, Apr 30 in the south)."""
    y, m = origin.dt.year, origin.dt.month
    north = np.where(m >= 11, y, y - 1)
    south = np.where(m >= 5, y, y - 1)
    return pd.Series(np.where(hemisphere == "S", south, north), index=origin.index)


def add_context_features(out: pd.DataFrame, ctx: Context) -> None:
    """Adds weather, supply and drinking-window columns in place (NaN where unknown)."""
    region = out["region"]
    vint = out["vintage_year"]

    # Weather: the wine's own vintage, and the latest completed harvest in its region.
    hemi = region.map(ctx.hemispheres)
    last_vint = _latest_harvest_vintage(out["origin"], hemi)
    if ctx.weather is not None:
        w = ctx.weather.set_index(["region", "vintage"])[WEATHER_VARS]
        own = w.reindex(pd.MultiIndex.from_arrays([region, vint])).to_numpy()
        latest = w.reindex(pd.MultiIndex.from_arrays([region, last_vint])).to_numpy()
        # A vintage's weather is only known once its season has ended.
        own[(vint > last_vint).to_numpy()] = np.nan
        for i, v in enumerate(WEATHER_VARS):
            out[f"vint_{v}"] = own[:, i]
            out[f"last_{v}"] = latest[:, i]
    else:
        for v in WEATHER_VARS:
            out[f"vint_{v}"] = out[f"last_{v}"] = np.nan

    # Supply: crop year Y is usable from May 1 of Y+1.
    published = (out["origin"] - pd.DateOffset(months=SUPPLY_LAG_MONTHS)).dt.year
    if ctx.supply is not None:
        s = ctx.supply.set_index(["region", "crop_year"])[["tons_yoy", "price_yoy"]]
        own = s.reindex(pd.MultiIndex.from_arrays([region, vint])).to_numpy()
        own[(vint > published).to_numpy()] = np.nan
        latest = s.reindex(pd.MultiIndex.from_arrays([region, published])).to_numpy()
        out["vint_tons_yoy"], out["vint_grape_price_yoy"] = own[:, 0], own[:, 1]
        out["last_tons_yoy"], out["last_grape_price_yoy"] = latest[:, 0], latest[:, 1]
    else:
        for c in FEATURE_GROUPS["supply"]:
            out[c] = np.nan

    # Brand momentum: the producer's other wines, excluding this one.
    if ctx.brand_stats is not None and "brand" in out:
        b = ctx.brand_stats.set_index(["date", "brand"])
        st = b.reindex(pd.MultiIndex.from_arrays([out["origin"], out["brand"]]))
        others = st["n_listed"].to_numpy() - 1
        ratio = lambda num, den: np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)  # noqa: E731
        out["brand_n_others"] = others
        out["brand_up_1q"] = ratio(st["n_up"].to_numpy() - out["own_up"].to_numpy(),
                                   st["n_valid"].to_numpy() - out["own_valid"].to_numpy())
        out["brand_up_4q"] = ratio(st["n_up_4"].to_numpy() - out["own_up_4"].to_numpy(),
                                   st["n_valid_4"].to_numpy() - out["own_valid_4"].to_numpy())
        out["brand_down_4q"] = ratio(st["n_down_4"].to_numpy() - out["own_down_4"].to_numpy(),
                                     st["n_valid_4"].to_numpy() - out["own_valid_4"].to_numpy())
        other_mean = ratio(st["sum_logp"].to_numpy() - out["log_price"].to_numpy(), others)
        out["brand_rel_price"] = out["log_price"].to_numpy() - other_mean
    else:
        for c in FEATURE_GROUPS["brand"]:
            out[c] = np.nan

    # Drinking window (vintage wines only).
    keys = list(zip(region.where(region.notna(), None), out["style"], out["tier"]))
    windows = {k: drinking_window(*k) for k in set(keys)}
    start = np.array([windows[k][0] for k in keys], dtype=float)
    end = np.array([windows[k][1] for k in keys], dtype=float)
    age = out["vintage_age"].to_numpy()
    out["years_to_window"] = start - age
    out["years_past_window"] = age - end
    out["in_window"] = np.where(np.isnan(age), np.nan, ((age >= start) & (age <= end)).astype(float))


def expand_horizons(origins: pd.DataFrame, periods: pd.DatetimeIndex, horizon: int, with_target: bool,
                    dates: list[pd.Timestamp] | None = None) -> pd.DataFrame:
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
            x["target_date"] = dates[h - 1]
        rows.append(x)
    return pd.concat(rows, ignore_index=True)
