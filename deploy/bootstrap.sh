#!/usr/bin/env bash
# First-boot setup for the Cellar Index server (Ubuntu 24.04, arm64). Run as root by EC2 user data:
#   bootstrap.sh <source-dir> <bundle-dir> <backup-bucket> <region>
# Installs PostgreSQL, Python, Node and nginx; restores the database and the active model; builds
# the Next.js site; and runs the API and site as systemd services behind nginx on port 80.
set -euxo pipefail
SRC_IN=$1
BUNDLE=$2
BACKUP_BUCKET=$3
REGION=$4
APP=/opt/cellar
SRC=$APP/src
export DEBIAN_FRONTEND=noninteractive

# ---- swap (the Next.js build needs more than 2 GB) -------------------------------------------
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---- packages ----------------------------------------------------------------------------------
apt-get update
apt-get install -y postgresql nginx python3.12-venv python3-dev build-essential curl ca-certificates
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# ---- app user and code -------------------------------------------------------------------------
id cellar >/dev/null 2>&1 || useradd --system --create-home --home-dir "$APP" --shell /usr/sbin/nologin cellar
rm -rf "$SRC" && mkdir -p "$SRC" && cp -a "$SRC_IN"/. "$SRC"/
mkdir -p "$SRC/ml/registry" && cp -a "$BUNDLE"/registry/. "$SRC/ml/registry/"
chown -R cellar:cellar "$APP"

# ---- database: restore the dump, point the registry at this machine --------------------------
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname = 'cellar'" | grep -q 1 || sudo -u postgres createuser cellar
sudo -u postgres dropdb --if-exists winetracker
sudo -u postgres createdb -O cellar winetracker
sudo -u cellar pg_restore --no-owner --role=cellar -d winetracker "$BUNDLE/winetracker.dump"
sudo -u cellar psql winetracker -c \
  "UPDATE model_runs SET artifact_uri = '$SRC/ml/registry/' || model_version || '/model.joblib'"

# ---- API (FastAPI + model service) --------------------------------------------------------------
cd "$SRC/backend"
sudo -u cellar python3.12 -m venv .venv
sudo -u cellar .venv/bin/pip install --quiet --upgrade pip
sudo -u cellar .venv/bin/pip install --quiet -r requirements.txt

cat > /etc/systemd/system/cellar-api.service <<UNIT
[Unit]
Description=Cellar Index API and model service
After=network.target postgresql.service
[Service]
User=cellar
WorkingDirectory=$SRC/backend
Environment=DATABASE_URL=postgresql+psycopg:///winetracker
Environment=CORS_ORIGINS=
ExecStart=$SRC/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --root-path /api/v1 --proxy-headers
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now cellar-api
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8000/health && break; sleep 2; done

# ---- website (Next.js) --------------------------------------------------------------------------
# The API must be up during the build: pages without search params are prerendered from it.
cd "$SRC/frontend"
sudo -u cellar npm ci --no-audit --no-fund
sudo -u cellar env API_URL=http://127.0.0.1:8000 NODE_OPTIONS=--max-old-space-size=1536 NEXT_TELEMETRY_DISABLED=1 npm run build

cat > /etc/systemd/system/cellar-web.service <<UNIT
[Unit]
Description=Cellar Index website
After=network.target cellar-api.service
[Service]
User=cellar
WorkingDirectory=$SRC/frontend
Environment=NODE_ENV=production
Environment=API_URL=http://127.0.0.1:8000
Environment=NEXT_TELEMETRY_DISABLED=1
ExecStart=/usr/bin/npm run start -- -p 3000 -H 127.0.0.1
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now cellar-web

# ---- nginx: / -> Next.js, /api/v1/ -> FastAPI (public API docs at /api/v1/docs) -----------------
cat > /etc/nginx/sites-available/cellar <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 1m;
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/cellar /etc/nginx/sites-enabled/cellar
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ---- nightly database backup to S3 (kept 30 days by the bucket's lifecycle rule) -----------------
cat > /etc/cron.d/cellar-backup <<CRON
AWS_DEFAULT_REGION=$REGION
15 7 * * * cellar pg_dump -Fc winetracker | /usr/local/bin/aws s3 cp - s3://$BACKUP_BUCKET/backups/winetracker-\$(date +\%F).dump --only-show-errors
CRON

for i in $(seq 1 60); do curl -sf http://127.0.0.1/ >/dev/null && break; sleep 2; done
curl -sf http://127.0.0.1/api/v1/health
echo "CELLAR BOOTSTRAP COMPLETE"
