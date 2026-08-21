#!bin/bash

set -e

# Two bugs in one line, and they cancelled the guard out entirely: the path is
# the Codespaces one, so it never matched a local devcontainer, and `-f` on what
# is always a directory never matched in Codespaces either. Everything below
# then ran on every rebuild -- `bench new-site dev.localhost` against a site that
# exists, and a `bench get-app crm` that would clone a second copy of the app
# over a tree that is a symlink to this repo. `set -e` aborted it partway, which
# is the only reason a rebuild has been survivable rather than destructive.
for bench_root in /workspace/frappe-bench /workspaces/frappe_codespace/frappe-bench; do
    if [[ -d "$bench_root/apps/frappe" ]]; then
        echo "Bench already exists at $bench_root, skipping init"
        exit 0
    fi
done

rm -rf /workspaces/frappe_codespace/.git

source /home/frappe/.nvm/nvm.sh
nvm alias default 18
nvm use 18

echo "nvm use 18" >> ~/.bashrc
cd /workspace

bench init \
    --ignore-exist \
    --skip-redis-config-generation \
    frappe-bench

cd frappe-bench

# Use containers instead of localhost
bench set-mariadb-host mariadb
bench set-redis-cache-host redis://redis-cache:6379
bench set-redis-queue-host redis://redis-queue:6379
bench set-redis-socketio-host redis://redis-socketio:6379

# Remove redis from Procfile
sed -i '/redis/d' ./Procfile


bench new-site dev.localhost \
    --mariadb-root-password 123 \
    --admin-password admin \
    --no-mariadb-socket

bench --site dev.localhost set-config developer_mode 1
bench --site dev.localhost clear-cache
bench use dev.localhost
bench get-app crm
bench --site dev.localhost install-app crm
