"""Growing-season weather per region and vintage, from NASA POWER (daily MERRA-2 reanalysis on a
~0.5 degree grid; free, no key). Open-Meteo's ERA5 archive is finer but its free tier counts a
35-year request as hundreds of calls; POWER's daily temperatures correlate 0.97 with ERA5 at
these sites, and a constant grid bias cancels out in the anomaly features.

    python -m ingest.weather download   # daily weather 1991-today per region -> data/raw/weather/
    python -m ingest.weather features   # -> data/processed/region_weather.csv (one row per region x vintage)

Seasons: northern-hemisphere vintage Y grows Apr-Oct of Y; southern vintage Y grows Oct Y-1 to Apr Y.
Anomalies are measured against each region's 1991-2020 normal, the standard climate baseline.
"""

import datetime as dt
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

from ingest.http import fetch
from ingest.regions import REGIONS

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "weather"
OUT = ROOT / "data" / "processed" / "region_weather.csv"
API = "https://power.larc.nasa.gov/api/temporal/daily/point"
# NASA POWER parameter -> column name used below
DAILY = {"T2M_MAX": "temperature_2m_max", "T2M_MIN": "temperature_2m_min", "T2M": "temperature_2m_mean",
         "PRECTOTCORR": "precipitation_sum"}
START = "19910101"
NORMAL_YEARS = (1991, 2020)

FEATURES = ["gdd", "gs_tmean", "gs_rain", "harvest_rain", "frost_days", "heat_days"]


def slug(region: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", region.lower()).strip("-")


def download(delay_s: float = 1.0) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    end = dt.date.today() - dt.timedelta(days=7)  # reanalysis lags by a few days
    for region, (lat, lon, _) in REGIONS.items():
        dest = RAW / f"{slug(region)}.csv"
        if dest.exists() and pd.read_csv(dest)["date"].max() >= end.isoformat():
            continue
        params = {"parameters": ",".join(DAILY), "community": "AG", "latitude": lat, "longitude": lon,
                  "start": START, "end": end.strftime("%Y%m%d"), "format": "JSON"}
        data = json.loads(fetch(f"{API}?{urllib.parse.urlencode(params)}", timeout=180))["properties"]["parameter"]
        df = pd.DataFrame({DAILY[k]: pd.Series(v) for k, v in data.items()}).replace(-999.0, np.nan)
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df.rename_axis("date").reset_index().assign(date=lambda d: d["date"].dt.date).to_csv(dest, index=False)
        print(f"{region}: {len(df)} days")
        time.sleep(delay_s)


def season_windows(hemisphere: str, vintage: int) -> dict[str, tuple[str, str]]:
    """Date windows for one vintage: full growing season, spring-frost window, harvest window."""
    if hemisphere == "N":
        y = vintage
        return {"season": (f"{y}-04-01", f"{y}-10-31"), "frost": (f"{y}-04-01", f"{y}-05-15"),
                "harvest": (f"{y}-09-01", f"{y}-10-31")}
    y0, y = vintage - 1, vintage
    return {"season": (f"{y0}-10-01", f"{y}-04-30"), "frost": (f"{y0}-10-01", f"{y0}-11-15"),
            "harvest": (f"{y}-03-01", f"{y}-04-30")}


def vintage_features(daily: pd.DataFrame, hemisphere: str, vintage: int) -> dict | None:
    w = season_windows(hemisphere, vintage)
    if daily.index.max() < pd.Timestamp(w["season"][1]):
        return None  # season not finished yet
    season = daily.loc[w["season"][0]:w["season"][1]]
    frost = daily.loc[w["frost"][0]:w["frost"][1]]
    harvest = daily.loc[w["harvest"][0]:w["harvest"][1]]
    return {
        # Growing degree days (base 10 C): heat available to ripen grapes (Winkler-style index).
        "gdd": float(np.clip(season["temperature_2m_mean"] - 10, 0, None).sum()),
        "gs_tmean": float(season["temperature_2m_mean"].mean()),
        "gs_rain": float(season["precipitation_sum"].sum()),
        # Rain at harvest brings rot and dilution; spring frost and heat spikes cut yields.
        "harvest_rain": float(harvest["precipitation_sum"].sum()),
        "frost_days": int((frost["temperature_2m_min"] < 0).sum()),
        "heat_days": int((season["temperature_2m_max"] > 35).sum()),
    }


def build_features() -> pd.DataFrame:
    rows = []
    for region, (_, _, hemisphere) in REGIONS.items():
        daily = pd.read_csv(RAW / f"{slug(region)}.csv", parse_dates=["date"]).set_index("date")
        first = daily.index.min().year + (1 if hemisphere == "S" else 0)
        for vintage in range(first, daily.index.max().year + 1):
            feats = vintage_features(daily, hemisphere, vintage)
            if feats:
                rows.append({"region": region, "vintage": vintage, **feats})
    df = pd.DataFrame(rows)
    normal = df[df["vintage"].between(*NORMAL_YEARS)].groupby("region")[FEATURES].mean()
    for f in FEATURES:
        df[f"{f}_anom"] = df[f] - df["region"].map(normal[f])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.round(2).to_csv(OUT, index=False)
    return df


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "features") == "download":
        download()
    else:
        f = build_features()
        print(f"{len(f)} region-vintages for {f['region'].nunique()} regions, vintages {f['vintage'].min()}-{f['vintage'].max()}")
