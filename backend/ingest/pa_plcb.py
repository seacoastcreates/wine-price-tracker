"""Pennsylvania Liquor Control Board (PLCB) quarterly Product Price Lists.

The PLCB is the state-run retailer for wine and spirits in Pennsylvania and publishes its full
retail price list every quarter (Act 39 of 2016). Reports go back to October 2016:
https://www.pa.gov/en/agencies/lcb/about-us/reports-and-publications/quarterly-price-listing.html

Each line is: code, description (incl. vintage), size, [sale start, sale end], [promo price], regular price.
Reports before October 2023 use upper-case descriptions, category headings, and no dot leaders;
the same pattern handles both formats.
Lines with a promo price and dates are temporary sales; a promo price without dates is a
clearance price.

    python -m ingest.pa_plcb download        # fetch any reports not already in data/raw/pa_plcb
    python -m ingest.pa_plcb parse           # -> data/processed/pa_plcb_prices.csv
"""

import csv
import datetime as dt
import re
import sys
import time
import urllib.request
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "pa_plcb"
OUT = ROOT / "data" / "processed" / "pa_plcb_prices.csv"
INDEX_URL = "https://www.pa.gov/en/agencies/lcb/about-us/reports-and-publications/quarterly-price-listing.html"
USER_AGENT = "Mozilla/5.0 (compatible; wine-price-tracker/0.1; research)"

MONEY = r"\$([\d,]+\.\d{2})"
DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"
SIZE = r"(?P<size>[\d.,]+\s*(?:ML|mL|L|OZ|oz|LTR)|EACH|KIT)"
PRICES = rf"(?:{DATE}\s+{DATE}\s+)?(?:(?:{MONEY}|\.{{3,}})\s+)?{MONEY}\s*$"
LINE = re.compile(rf"^\s*(?P<code>\d{{3,}})\s+(?P<desc>.+?)\s+{SIZE}\s+{PRICES}")
# Long names wrap: the name sits on the (up to two) lines above a "code size price" line.
ORPHAN = re.compile(rf"^\s*(?P<code>\d{{3,}})\s+{SIZE}\s+{PRICES}")
NOT_NAME = re.compile(r"^(Code Size|Pennsylvania Liquor|Retail prices|Wholesale prices|due to limited|\d+/\d+/\d{4} )")
VINTAGE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
FIELDS = ["report_date", "code", "description", "vintage", "size", "regular_price",
          "promo_price", "promo_type", "sale_start", "sale_end"]


def report_urls() -> list[str]:
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": USER_AGENT})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    urls = {u.replace("http://", "https://") for u in re.findall(r"https?://[^\"']*CRO000002_Report_\d{8}\.pdf", html)}
    return sorted(urls)


def download(delay_s: float = 5.0) -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    fetched = []
    for url in report_urls():
        dest = RAW / url.rsplit("/", 1)[1]
        if dest.exists() and dest.read_bytes()[:4] == b"%PDF":
            continue
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        dest.write_bytes(urllib.request.urlopen(req, timeout=180).read())
        fetched.append(dest)
        time.sleep(delay_s)
    return fetched


def normalize_size(size: str) -> str:
    """'1.750 L', '0.75 L', '750 mL' -> '1750 ML', '750 ML', '750 ML' so both report formats match."""
    m = re.match(r"([\d.,]+)\s*(ML|L|LTR|OZ)$", size.upper().replace(" ", " "))
    if not m:
        return size.upper()
    qty = float(m.group(1).replace(",", ""))
    ml = qty * {"ML": 1, "L": 1000, "LTR": 1000, "OZ": 29.5735}[m.group(2)]
    return f"{round(ml)} ML"


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    m, d, y = (int(x) for x in s.split("/"))
    return dt.date(y + 2000 if y < 100 else y, m, d).isoformat()


def parse_report(path: Path) -> tuple[list[dict], int]:
    """Returns parsed rows and the count of product-looking lines that failed to parse."""
    report_date = dt.datetime.strptime(path.stem.rsplit("_", 1)[1], "%Y%m%d").date().isoformat()
    pdf = pdfium.PdfDocument(path)
    rows, misses = [], 0
    for i in range(len(pdf)):
        pending: list[str] = []
        for line in pdf[i].get_textpage().get_text_range().splitlines():
            if m := ORPHAN.match(line):
                if not pending:
                    misses += 1
                    continue
                code, size, start, end, promo, regular = m.groups()
                desc = " ".join(pending[-2:])
            elif m := LINE.match(line):
                code, desc, size, start, end, promo, regular = m.groups()
            else:
                if re.match(r"^\s*\d{3,}\s+\S", line) and "$" in line:
                    misses += 1
                elif line.strip() and not NOT_NAME.match(line.strip()):
                    pending.append(line.strip())
                continue
            pending = []
            vintage = VINTAGE.findall(desc)
            rows.append({
                "report_date": report_date,
                "code": code,
                "description": desc.strip(),
                "vintage": vintage[-1] if vintage else ("NV" if "nonvintage" in desc.lower() else ""),
                "size": normalize_size(re.sub(r"\s+", " ", size)),
                "regular_price": regular.replace(",", ""),
                "promo_price": promo.replace(",", "") if promo else "",
                "promo_type": ("sale" if start else "clearance") if promo else "",
                "sale_start": parse_date(start) or "",
                "sale_end": parse_date(end) or "",
            })
    return rows, misses


def parse_all() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for path in sorted(RAW.glob("CRO000002_Report_*.pdf")):
            rows, misses = parse_report(path)
            w.writerows(rows)
            print(f"{path.name}: {len(rows):>6} rows, {misses} unparsed product lines")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "parse"
    if cmd == "download":
        print(f"Downloaded {len(download())} new reports")
    else:
        parse_all()
