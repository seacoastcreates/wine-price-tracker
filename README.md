# Cellar Index: wine price tracker and forecaster

Ten years of **real, official shelf prices** for ~25,000 wines, including 8,400 on sale today. Each wine gets a model-based
estimate of its chance of a price rise or cut over the next year.

| Layer | Tech |
|---|---|
| Frontend | Next.js 16 (App Router, server components), Tailwind v4, Recharts |
| API | FastAPI on Python 3.12 (Mangum adapter for Lambda) |
| Database | PostgreSQL: `wines`, `price_observations`, `model_runs`, `forecasts` |
| Ingestion | PDF price lists parsed with pypdfium2 |
| ML | scikit-learn gradient boosting (classifier + quantile regressors), run as a SageMaker training job |

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
3. **Link** (`load.py`). A union-find joins rows into one wine when they share a PLCB code (the same product under a rewritten
   description) or a normalized name at the same size (the same wine in a new vintage). A few famous wines that were renamed
   several times are joined through `db/featured.json`.

## Model
Wine list prices are sticky: **about 4% change in a given quarter**. When a price rises, the typical increase is about 7%.
There are also statewide shocks; in April 2023, 31% of wines rose at once. Predicting "price stays the same" is almost always
right, so the useful question is **which wines are about to move**.

- **Price-change classifier.** P(higher), P(lower) and P(same) at 1–4 quarters ahead, with separate models for the typical
  size of a rise or a cut. Features include past changes, time since the last change, sale and clearance status, discount
  depth, how long the wine has been listed, price level, style and tier. All models are global (one across every wine) and
  predict each horizon directly.
- **Calibration.** Probabilities are recalibrated with Platt scaling on the most recent quarters, and the p10/p90 price range
  uses conformalized quantile regression.
- **Evaluation.** A time-based holdout on the last 4 quarters, with no leakage, scored against the base rate:

| Horizon | Rise AUC | Rise AP (base rate) | Cut AUC |
|---|---|---|---|
| 1 quarter | 0.79 | 0.058 (0.016) | 0.73 |
| 4 quarters | 0.73 | 0.093 (0.044) | 0.62 |

  The model ranks well: flagged wines are 2–4× more likely to change price than average. Absolute probabilities at 3–4
  quarters run high (9% predicted vs 4.4% actual) because price rises slowed after 2024, and any recent calibration window
  still overstates them. This non-stationarity is a known limitation.

## Run locally
```bash
createdb winetracker
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r ingest/requirements.txt pandas scikit-learn
cd .. && ./refresh.sh                      # download, parse, load, train, publish forecasts (~10 min)
cd backend && .venv/bin/uvicorn app.main:app --reload          # http://localhost:8000/docs
cd ../frontend && npm install && npm run dev                   # http://localhost:3000
```

## Roadmap
1. AWS deploy (CDK, Python): Amplify Hosting, Lambda and API Gateway, Aurora Serverless v2, and a SageMaker training job run
   each quarter by EventBridge when a new price list is published.
2. More sources for more frequent data, such as other state-run retailers or retailer product pages that allow crawling.
3. Bedrock summaries that explain in plain English why a price is likely to move.
