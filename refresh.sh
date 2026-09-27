#!/usr/bin/env bash
# Full data + model refresh: fetch new PLCB price lists, rebuild the wine table, retrain, publish forecasts.
set -euo pipefail
cd "$(dirname "$0")/backend"
PY=.venv/bin/python
$PY -m ingest.pa_plcb download
$PY -m ingest.pa_plcb parse
$PY -m ingest.load
$PY -m scripts.ml_io export ../ml/data/series.csv
(cd ../ml && rm -rf artifacts && ../backend/.venv/bin/python train.py)
$PY -m scripts.ml_io load ../ml/artifacts
