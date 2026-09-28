#!/usr/bin/env bash
# Full data + model refresh: fetch new PLCB price lists, weather and crush data, rebuild the wine table,
# retrain both models, publish forecasts. (ml/ablation.py re-runs the feature experiments; it is slow.)
set -euo pipefail
cd "$(dirname "$0")/backend"
PY=.venv/bin/python
$PY -m ingest.pa_plcb download
$PY -m ingest.pa_plcb parse
$PY -m ingest.load
$PY -m ingest.weather download && $PY -m ingest.weather features
$PY -m ingest.ca_crush download && $PY -m ingest.ca_crush parse
$PY -m scripts.ml_io export ../ml/data/series.csv
(cd ../ml && rm -rf artifacts && ../backend/.venv/bin/python train.py && ../backend/.venv/bin/python train_vintage.py && ../backend/.venv/bin/python train_fair.py)
$PY -m scripts.ml_io load ../ml/artifacts
