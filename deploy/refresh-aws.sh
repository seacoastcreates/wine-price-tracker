#!/usr/bin/env bash
# Quarterly refresh on the server, started by an EventBridge Scheduler -> SSM Run Command schedule
# (or by hand: sudo /opt/cellar/src/deploy/refresh-aws.sh). Ingests the new PLCB price list and the
# latest weather and crush data, retrains all models on SageMaker, activates the new model (the API
# picks it up within a minute), and takes a fresh database backup.
set -euo pipefail
set -a; . /etc/cellar/cellar.env; set +a
cd /opt/cellar/src/backend
as_app() { sudo -u cellar --preserve-env=AWS_REGION,AWS_DEFAULT_REGION,ARTIFACT_BUCKET,SAGEMAKER_ROLE_ARN,TRAIN_IMAGE_URI,TRAIN_INSTANCE_TYPE,DATABASE_URL "$@"; }
PY=.venv/bin/python
echo "== $(date -u +%FT%TZ) refresh started"
# Raw downloads are cached in S3 so a fresh server only fetches what is new (and we stay polite to
# the PLCB, NASA and USDA sites).
RAW=/opt/cellar/src/data/raw
as_app mkdir -p "$RAW"
as_app /usr/local/bin/aws s3 sync "s3://$ARTIFACT_BUCKET/data/raw/" "$RAW/" --only-show-errors
as_app $PY -m ingest.pa_plcb download
as_app $PY -m ingest.pa_plcb parse
as_app $PY -m ingest.load
as_app $PY -m ingest.weather download
as_app $PY -m ingest.weather features
as_app $PY -m ingest.ca_crush download
as_app $PY -m ingest.ca_crush parse
as_app /usr/local/bin/aws s3 sync "$RAW/" "s3://$ARTIFACT_BUCKET/data/raw/" --only-show-errors
as_app $PY -m scripts.sagemaker_train
sudo -u cellar pg_dump -Fc winetracker | /usr/local/bin/aws s3 cp - "s3://$BACKUP_BUCKET/backups/winetracker-$(date +%F)-refresh.dump" --only-show-errors
echo "== $(date -u +%FT%TZ) refresh complete"
