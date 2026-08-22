#!/bin/bash
set -e

# The fork this checkout belongs to. `bench get-app crm` without a URL fetches
# upstream frappe/crm, which contains none of this repo's code.
CRM_REPO="${CRM_REPO:-https://github.com/Absolute-Insight/simcrm.git}"
CRM_BRANCH="${CRM_BRANCH:-main}"
# Matches MYSQL_ROOT_PASSWORD in docker-compose.yml; dev-only default.
MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-123}"

if [ -d "/home/frappe/frappe-bench/apps/frappe" ]; then
    echo "Bench already exists, skipping init"
    cd frappe-bench
    bench start
    # bench start only returns when the processes stop; do not fall through
    # into a second `bench init` against the existing directory.
    exit 0
else
    echo "Creating new bench..."
fi

bench init --skip-redis-config-generation frappe-bench --version version-15

cd frappe-bench

# Use containers instead of localhost
bench set-mariadb-host mariadb
bench set-redis-cache-host redis://redis:6379
bench set-redis-queue-host redis://redis:6379
bench set-redis-socketio-host redis://redis:6379

# Remove redis, watch from Procfile
sed -i '/redis/d' ./Procfile
sed -i '/watch/d' ./Procfile

bench get-app crm "$CRM_REPO" --branch "$CRM_BRANCH"

bench new-site crm.localhost \
    --force \
    --mariadb-root-password "$MARIADB_ROOT_PASSWORD" \
    --admin-password admin \
    --no-mariadb-socket

bench --site crm.localhost install-app crm
bench --site crm.localhost set-config developer_mode 1
bench --site crm.localhost set-config mute_emails 1
bench --site crm.localhost set-config server_script_enabled 1
bench --site crm.localhost clear-cache
bench use crm.localhost

bench start