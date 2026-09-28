#!/usr/bin/env bash
# Build the data bundle the server restores on first boot: a PostgreSQL dump and the active
# model's registry folder. Run before `cdk deploy` (see infra/README section in the main README).
set -euo pipefail
cd "$(dirname "$0")/.."
DB=${DB:-winetracker}
OUT=deploy/bundle
rm -rf "$OUT" && mkdir -p "$OUT/registry"
pg_dump --format=custom --no-owner --no-privileges "$DB" > "$OUT/winetracker.dump"
VERSION=$(psql -At "$DB" -c "SELECT model_version FROM model_runs WHERE is_active")
cp -R "ml/registry/$VERSION" "$OUT/registry/$VERSION"
echo "$VERSION" > "$OUT/ACTIVE_MODEL"
du -sh "$OUT"/* | sed 's/^/  /'
echo "Bundle ready for model $VERSION"
