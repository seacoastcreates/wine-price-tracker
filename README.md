# Cellar Index: wine price tracker and forecaster

Ten years of **real, official shelf prices** for ~31,000 wines (each vintage counted separately), including about 10,000
on sale today. Each wine gets a model-based
estimate of its chance of a price rise or cut over the next year.

| Layer | Tech |
|---|---|
| Frontend | Next.js 16 (App Router, server components), Tailwind v4, Recharts |
| API / model service | FastAPI on Python 3.12: data endpoints plus online inference and what-if scoring |
| Database | PostgreSQL: `wines`, `price_observations`, `model_runs`, `forecasts` |
| Ingestion | PDF price lists parsed with pypdfium2 |
| ML | `wineprice` package (scikit-learn gradient boosting), shared by the training job and the API |

## Data
The source is the **Pennsylvania Liquor Control Board's quarterly Product Price Lists**
([index](https://www.pa.gov/en/agencies/lcb/about-us/reports-and-publications/quarterly-price-listing.html)). The PLCB is the
state-run retailer, and Act 39 of 2016 requires it to publish the full retail price list every quarter. There are 40 reports, from
October 2016 to July 2026, and each has about 12,000–15,000 lines: code, description, size, regular price, and any sale or
clearance price. This is public government data, downloaded at a polite rate.

Pipeline (`backend/ingest/`):
1. **Parse** (`pa_plcb.py`). Handles two report layouts (the format changed in Oct 2023) and names that wrap onto
   extra lines. 508k rows are parsed, with 39 left unparsed.
2. **Classify** (`classify.py`). The lists have no category column, so keyword rules separate wine from spirits and accessories
   and assign a style (red, white, rosé, sparkling or dessert).
3. **Link** (`load.py`). **A wine is one vintage of one product at one bottle size**, so Caymus 2019 and Caymus 2020 are
   different wines, each with its own price history. Within a vintage, a union-find joins rows that share a PLCB code (codes are
   vintage-specific and survive the October 2023 description rewrite) or a normalized name. Vintages of the same product are
   grouped as a `family`, so each wine page lists its other vintages. About 30% of rows print no vintage. These are true
   non-vintage wines (such as Champagne NV) or everyday wines whose vintage the PLCB doesn't record, and each is tracked as
   one "NV" series.

## External data and feature experiments
- **Regions** (`backend/ingest/regions.py`): a gazetteer maps words in wine names to 49 growing regions with vineyard
  coordinates. It covers 67% of wines.
- **Weather** (`ingest/weather.py`): daily NASA POWER reanalysis from 1991 per region. For each vintage it computes
  growing degree days, spring frost days, heatwave days, harvest rain and season rain, as anomalies against the region's
  1991–2020 normal. It captures 2003's heat, the April 2021 frost in Champagne and Burgundy, and Napa's hot 2020. It
  misses very local frost (such as Bordeaux in 2017) because of the roughly 50 km grid.
- **Supply** (`ingest/ca_crush.py`): the USDA California Grape Crush Report, giving tons crushed and grower price per ton by
  district, 2009–2025. For example, Napa's 2020 crush was down 38%.
- **Drinking windows** (`ml/wineprice/windows.py`): rule-of-thumb aging windows by region, style and tier. Critics'
  per-wine windows are copyrighted.
- **Point in time:** a vintage's weather is used only after its season ends, and a crop's supply data only from May 1 of
  the following year, when the report is out.
- **Ablation** (`ml/ablation.py`, `ml/train_vintage.py`, and the Model page):
  - The drinking window improves the price-change model for vintage wines (rises within a year: AUC 0.771 → 0.808).
    It's adopted.
  - Weather helps predict cuts but hurts rise ranking. It isn't adopted.
  - Supply lowers next-vintage error in all 4 rolling test years, by about 1%. It's adopted in the next-vintage model.
  - Weather's effect on next-vintage pricing flips sign between test years, so it's kept as data but not used.

### Experiment 2: brand momentum and wine attributes
- **Brand** (`ml/wineprice/attributes.py`): the producer is parsed from each name ("Caymus", "Kim Crawford",
  "Chateau Margaux") and matched across the old all-caps and new name formats. Features are computed point in time,
  excluding the wine itself: the share of the brand's *other* wines raised or cut last quarter and last year, and this
  wine's price relative to the brand's.
- **Attributes:** grape variety (named, or implied by the appellation, such as Barolo → Nebbiolo), found for about 75%
  of wines, and classification (Grand Cru Classé, Grand Cru, Premier Cru, Reserva/Riserva, DOCG and so on).
- **Result:**
  - On the latest holdout year, brand momentum raised rise ranking (within a year: 0.838 → 0.851).
  - On the earlier holdout year (Oct 2024–Jul 2025), it made every comparison *worse* (0.813 → 0.807). The likely cause
    is the April 2023 statewide increase, which teaches the model that whole brands move together.
  - Attributes hurt in both the price-change model and the next-vintage model, where the high-cardinality grape
    category overfits about 4,900 transitions.
  - Neither is adopted. The columns stay in `wines` (`brand`, `grape`, `classification`) for display and for future
    models, such as the fair-price model.

## Next-vintage model
`ml/wineprice/vintage.py` predicts how a wine's next vintage will be priced against the current one. It's trained on
about 4,900 past vintage changes, of which 42% arrived priced higher. It beats "same price" in all 4 rolling test years,
by 4–21% in mean absolute error, with rise AUC around 0.77. Each wine page shows this outlook, together with the
drinking window, in its collector's view.

## Model
Wine list prices are sticky: **about 3% of wines change list price in a given quarter**. When vintages were merged, this looked
like 4.4%, because a new vintage arriving at a new price counted as a price change. When a price rises, the typical increase is
about 7%.
There are also statewide shocks; in April 2023, 31% of wines rose at once. Predicting "price stays the same" is almost always
right, so the useful question is **which wines are about to move**.

- **Price-change classifier.** P(higher), P(lower) and P(same) at 1–4 quarters ahead, with separate models for the typical
  size of a rise or a cut. Features include past changes, time since the last change, sale and clearance status, discount
  depth, how long the wine has been listed, years since the vintage, price level, style and tier. All models are global (one across every wine) and
  predict each horizon directly.
- **Calibration.** Probabilities are recalibrated with Platt scaling on the most recent quarters, and the p10/p90 price range
  uses conformalized quantile regression.
- **Evaluation.** A time-based holdout on the last 4 quarters, with no leakage, scored against the base rate:

| Horizon | Rise AUC | Rise AP (base rate) | Cut AUC |
|---|---|---|---|
| 1 quarter | 0.89 | 0.068 (0.011) | 0.85 |
| 4 quarters | 0.84 | 0.087 (0.026) | 0.84 |

  The model ranks well: flagged wines are 3–6× more likely to change price than average. Absolute probabilities of a rise at
  3–4 quarters run high (4.7% predicted vs 2.6% actual) because price rises slowed after 2024, and any recent calibration
  window still overstates them. This non-stationarity is a known limitation.

## ML backend
The model isn't just a batch job whose output gets read back. The API serves it.

- **One feature pipeline.** `ml/wineprice/` holds the feature engineering, models and a single `WinePriceModel.forecast()`
  method. The training job (`ml/train.py`) and the API (`backend/app/inference.py`) both call it, so training and serving
  can't drift apart.
- **Model registry.** Each training run is saved to an immutable per-version folder (or S3). `model_runs` records its metrics
  and `artifact_uri`, with exactly one run active at a time. The API loads the active artifact at startup and swaps in a newly
  activated model within 60 seconds, with no restart.
- **Online inference.** `GET /wines/{slug}/predict` scores a wine live from its current price history in about 110 ms.
- **What-if scoring.** `POST /wines/{slug}/predict` takes a scenario, for example
  `{"promo": "clearance", "discount_pct": 40}` or `{"list_price": 109.99}`. It applies the scenario to today's
  price-list entry and returns the forecast before and after. This powers the "What if?" panel on each wine page.
- **Explainability.** Permutation feature importance is computed on the holdout set at training time and shown on the Model
  page. Years since the vintage dominates.
- **Tests** (`backend/tests`). The parity test checks that online predictions match the stored batch forecasts for a random
  sample of wines, which guards against training/serving skew. API tests cover response shape, scenarios, validation, and
  delisted or unknown wines.

## Run locally
```bash
createdb winetracker
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r ingest/requirements.txt -r requirements-dev.txt -e ../ml
cd .. && ./refresh.sh                      # download, parse, load, train, publish forecasts (~10 min)
cd backend && .venv/bin/uvicorn app.main:app --reload          # http://localhost:8000/docs
cd ../frontend && npm install && npm run dev                   # http://localhost:3000
cd ../backend && .venv/bin/python -m pytest tests               # parity + API tests
```

## Roadmap
1. AWS deploy (CDK, Python): Amplify Hosting, Lambda and API Gateway, Aurora Serverless v2, and a SageMaker training job run
   each quarter by EventBridge when a new price list is published.
2. More sources for more frequent data, such as other state-run retailers or retailer product pages that allow crawling.
3. Bedrock summaries that explain in plain English why a price is likely to move, served as another API endpoint.
