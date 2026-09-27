-- Wine Price Tracker schema (PostgreSQL 15+)

-- One row per wine product at a given bottle size, followed across vintages.
CREATE TABLE IF NOT EXISTS wines (
    id             SERIAL PRIMARY KEY,
    slug           TEXT UNIQUE NOT NULL,
    name           TEXT NOT NULL,
    size           TEXT NOT NULL,
    style          TEXT NOT NULL CHECK (style IN ('red', 'white', 'rose', 'sparkling', 'dessert')),
    tier           TEXT NOT NULL CHECK (tier IN ('everyday', 'premium', 'luxury')),
    latest_vintage TEXT,
    source_codes   TEXT[] NOT NULL DEFAULT '{}',
    is_featured    BOOLEAN NOT NULL DEFAULT FALSE,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE   -- listed in the most recent price list
);

-- One row per wine per price list. regular_price is the list price; promo_price is a
-- temporary sale ('sale', with dates) or a clearance markdown ('clearance').
CREATE TABLE IF NOT EXISTS price_observations (
    wine_id       INTEGER NOT NULL REFERENCES wines(id) ON DELETE CASCADE,
    observed_on   DATE NOT NULL,
    source        TEXT NOT NULL,
    source_code   TEXT NOT NULL,
    vintage       TEXT,
    regular_price NUMERIC(10, 2) NOT NULL CHECK (regular_price > 0),
    promo_price   NUMERIC(10, 2),
    promo_type    TEXT CHECK (promo_type IN ('sale', 'clearance')),
    sale_start    DATE,
    sale_end      DATE,
    PRIMARY KEY (wine_id, observed_on, source)
);

CREATE TABLE IF NOT EXISTS model_runs (
    model_version TEXT PRIMARY KEY,
    trained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    algorithm     TEXT NOT NULL,
    horizon       INTEGER NOT NULL,
    horizon_unit  TEXT NOT NULL,
    metrics       JSONB NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT FALSE
);

-- At most one active model at a time.
CREATE UNIQUE INDEX IF NOT EXISTS model_runs_one_active
    ON model_runs (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS forecasts (
    model_version TEXT NOT NULL REFERENCES model_runs(model_version) ON DELETE CASCADE,
    wine_id       INTEGER NOT NULL REFERENCES wines(id) ON DELETE CASCADE,
    target_date   DATE NOT NULL,
    p10           NUMERIC(10, 2) NOT NULL,
    p50           NUMERIC(10, 2) NOT NULL,
    p90           NUMERIC(10, 2) NOT NULL,
    p_up          REAL NOT NULL,    -- probability the list price is higher than today by target_date
    p_down        REAL NOT NULL,
    up_pct        REAL NOT NULL,    -- typical size of a rise / cut, in percent
    down_pct      REAL NOT NULL,
    PRIMARY KEY (model_version, wine_id, target_date)
);

CREATE INDEX IF NOT EXISTS wines_name_trgm ON wines (lower(name));
