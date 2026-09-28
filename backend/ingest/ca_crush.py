"""California Grape Crush Report (USDA NASS): wine-grape tons crushed and grower price per ton,
by grape pricing district, for each crop year. A short crop or a jump in grape prices is an
early signal of supply-driven retail price rises.

    python -m ingest.ca_crush download   # final reports 2009+ -> data/raw/ca_crush/
    python -m ingest.ca_crush parse      # -> data/processed/ca_supply.csv (region x crop year)

The final report for crop year Y is published by April 30 of Y+1, so features built from it are
only used from May 1 of Y+1 onward.
"""

import io
import re
import sys
import time
import urllib.parse
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from ingest.http import fetch

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ca_crush"
OUT = ROOT / "data" / "processed" / "ca_supply.csv"
INDEX = ("https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/"
         "Grapes/Crush/Reports/index.php")
FIRST_CROP = 2009

# Our growing regions -> grape pricing district ("state" = statewide total).
DISTRICTS = {
    "Sonoma": "3", "Napa Valley": "4", "Monterey": "7", "Paso Robles": "8", "Santa Barbara": "8",
    "Central Coast": "8", "Lodi": "11", "California Central Valley": "state",
}


def download(delay_s: float = 3.0) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    html = fetch(INDEX, timeout=60).decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="(\.\./Final/(\d{4})/[^"]+\.zip)"', html)))
    for href, folder in links:
        if int(folder) < FIRST_CROP:
            continue
        dest = RAW / f"{folder}__{Path(href).name.replace(' ', '_')}"
        if dest.exists():
            continue
        url = urllib.parse.urljoin(INDEX, urllib.parse.quote(href, safe="/.:"))
        dest.write_bytes(fetch(url, timeout=180))
        print(f"downloaded {dest.name}")
        time.sleep(delay_s)


def total_wine_by_district(sheet: pd.DataFrame) -> tuple[int, dict[str, float]]:
    """Crop year and the TOTAL WINE row of a table laid out as variety rows x district columns."""
    text = " ".join(str(v) for v in sheet.iloc[:4, 0].dropna())
    crop = int(re.search(r"(\d{4}) CROP", text.upper()).group(1))
    header_row = sheet.index[sheet.iloc[:, 0].astype(str).str.startswith("Type and Var")][0]
    total_row = sheet.index[sheet.iloc[:, 0].astype(str).str.strip().str.upper() == "TOTAL WINE"][0]
    values = {}
    for col in sheet.columns[1:]:
        head = sheet.at[header_row, col]
        val = pd.to_numeric(sheet.at[total_row, col], errors="coerce")
        if pd.isna(val):
            continue
        if isinstance(head, (int, float)) and not pd.isna(head):
            values[str(int(head))] = float(val)
        elif isinstance(head, str) and "STATE" in head.upper():
            values["state"] = float(val)
    return crop, values


def read_table(zf: zipfile.ZipFile, number: str) -> pd.DataFrame | None:
    name = next((n for n in zf.namelist() if re.search(rf"tb{number}\.xlsx?$", n, re.I)), None)
    if name is None:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(io.BytesIO(zf.read(name)), header=None)


def parse() -> pd.DataFrame:
    by_crop: dict[int, dict] = {}
    for path in sorted(RAW.glob("*.zip")):  # later files for the same crop year overwrite earlier ones
        with zipfile.ZipFile(path) as zf:
            tons_sheet, price_sheet = read_table(zf, "02"), read_table(zf, "06")
            if tons_sheet is None or price_sheet is None:
                continue
            crop, tons = total_wine_by_district(tons_sheet)
            crop_p, price = total_wine_by_district(price_sheet)
            if crop != crop_p:
                continue
            if "state" not in tons:
                tons["state"] = sum(v for k, v in tons.items() if k != "state")
            by_crop[crop] = {"tons": tons, "price": price}

    rows = []
    for crop, d in sorted(by_crop.items()):
        for region, district in DISTRICTS.items():
            rows.append({"region": region, "crop_year": crop, "district": district,
                         "tons": d["tons"].get(district), "price_per_ton": d["price"].get(district)})
    df = pd.DataFrame(rows).sort_values(["region", "crop_year"])
    g = df.groupby("region")
    df["tons_yoy"] = np.log(df["tons"] / g["tons"].shift(1))
    df["price_yoy"] = np.log(df["price_per_ton"] / g["price_per_ton"].shift(1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(OUT, index=False)
    return df


if __name__ == "__main__":
    if (sys.argv[1] if len(sys.argv) > 1 else "parse") == "download":
        download()
    else:
        df = parse()
        print(f"{df['crop_year'].nunique()} crop years ({df['crop_year'].min()}-{df['crop_year'].max()}) "
              f"for {df['region'].nunique()} regions")
