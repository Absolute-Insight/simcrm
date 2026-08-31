#!/bin/bash
#
# Devcontainer provisioning, run once per container as postCreateCommand.
#
# Written to be re-runnable by hand:  bash /workspace/scripts/init.sh
# Every step is guarded, so a run that died halfway resumes where it stopped and
# a run against a finished bench is a no-op. That matters because postCreate
# output scrolls past in the Dev Containers terminal and a failure here is
# otherwise silent -- you get a container that built fine and has no bench in it.

set -euo pipefail

REPO=/workspace
BENCH=/home/frappe/frappe-bench
SITE=dev.localhost
NODE_VERSION=24
LOG="$REPO/.devcontainer/init.log"

exec > >(tee -a "$LOG") 2>&1
trap 'echo >&2; echo "init.sh FAILED at line $LINENO. Log: .devcontainer/init.log" >&2; echo "Re-run with: bash /workspace/scripts/init.sh" >&2' ERR

step() { printf '\n=== %s\n' "$*"; }
echo "--- $(date -Is) ---"

# Every bench command registers bench.utils.check_latest_version as an atexit
# hook, and that does a `requests.get("https://pypi.org/pypi/frappe-bench/json")`
# with no timeout argument. Egress to some of pypi's Fastly addresses is dropped
# from this network, so the connect sat in SYN_SENT until the kernel gave up --
# 45 to 90 seconds *per bench invocation*, which turned provisioning into a
# twenty-minute stall indistinguishable from a hang. FRAPPE_DOCKER_BUILD is the
# early return the function already offers; nothing here wants a version check.
export FRAPPE_DOCKER_BUILD=1

# Separately: the image exports this from ~/.bashrc, which Ubuntu's skeleton
# returns out of before reaching the line whenever the shell is non-interactive
# -- i.e. every time postCreateCommand runs. It suppresses bench's "not installed
# in editable mode" nag, which is noise in a dev bench.
export BENCH_DEVELOPER=1

# The bench is a named docker volume mounted here, not a directory in the
# bind-mounted repo. Docker creates a volume's mount point root-owned whenever
# the path does not exist in the image, so claim it before anything runs as
# frappe.
step "Claiming $BENCH"
[[ -w $BENCH ]] || sudo chown "$(id -u):$(id -g)" "$BENCH"

# VS Code copies the host ~/.gitconfig into the container, and this host's
# carries `credential.https://github.com.helper = !/usr/bin/gh auth
# git-credential`. gh is not installed in this image, and a per-host helper
# outranks the generic proxy VS Code installs in /etc/gitconfig -- so every
# authenticated github fetch in here dies with "could not read Username for
# 'https://github.com'". Drop the dead entries and let VS Code's proxy answer.
step "Repairing git credential helpers"
for host in https://github.com https://gist.github.com; do
    if git config --global --get-all "credential.${host}.helper" 2>/dev/null | grep -q 'gh auth'; then
        git config --global --unset-all "credential.${host}.helper"
    fi
done

# `frappe/bench:latest` is a moving tag and no longer ships node 18: it carries
# v22 and v24, with v24 as the default. `nvm use 18` failed outright ("N/A:
# version v18 is not yet installed") and took the whole script with it.
#
# 24, not 22. The pinned frappe's package.json declares engines node ">=24", and
# `bench init` runs `yarn install --check-files` inside apps/frappe, which honours
# that and stops with "The engine node is incompatible with this module" -- then
# bench offers a rollback prompt nothing can answer under postCreate and aborts,
# leaving a half-built bench. frontend/package.json asks for
# "^20.19.0 || >=22.12.0", so 24 satisfies this repo as well as the framework.
# `nvm install` is a no-op when the version is already present, so this survives
# the tag moving again.
step "Node $NODE_VERSION"
source /home/frappe/.nvm/nvm.sh
nvm install "$NODE_VERSION"
nvm alias default "$NODE_VERSION"
nvm use "$NODE_VERSION"
grep -qxF "nvm use $NODE_VERSION" ~/.bashrc || echo "nvm use $NODE_VERSION" >> ~/.bashrc

# shellcheck source=./frappe-pin.env
source "$REPO/scripts/frappe-pin.env"

# Same helper CI uses, so the bench you develop against and the bench the suite
# runs against are the same frappe commit by construction.
step "Frappe source at $FRAPPE_REF"
FRAPPE_SRC=/tmp/frappe
bash "$REPO/scripts/fetch-frappe.sh" "$FRAPPE_SRC"

step "Bench"
# bench init is not resumable. When it fails partway it asks whether to roll
# back, gets no answer under postCreate, and aborts with apps/frappe, env/ and a
# Procfile already on disk -- so testing for those would make the next run skip
# init and build on the wreckage. Completion gets its own marker instead, and a
# failed attempt is cleared rather than reused.
if [[ -f $BENCH/.init-complete ]]; then
    echo "already initialised, skipping"
else
    if [[ -n "$(ls -A "$BENCH" 2>/dev/null)" ]]; then
        if compgen -G "$BENCH/sites/*/site_config.json" >/dev/null; then
            echo "$BENCH holds sites but never finished bench init." >&2
            echo "Refusing to clear it -- sort it out by hand." >&2
            exit 1
        fi
        echo "clearing a partial bench"
        find "$BENCH" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    fi
    cd "$(dirname "$BENCH")"
    bench init \
        --ignore-exist \
        --skip-redis-config-generation \
        --frappe-path "$FRAPPE_SRC" \
        --frappe-branch "$FRAPPE_PIN_BRANCH" \
        "$(basename "$BENCH")"
    touch "$BENCH/.init-complete"
fi

cd "$BENCH"

# Use containers instead of localhost
step "Service hosts"
bench set-mariadb-host mariadb
bench set-redis-cache-host redis://redis-cache:6379
bench set-redis-queue-host redis://redis-queue:6379
bench set-redis-socketio-host redis://redis-socketio:6379

# Redis runs as its own compose services, not under this Procfile
sed -i '/redis/d' ./Procfile

# `bench serve` binds 127.0.0.1 by default, which the compose `ports:` mapping
# cannot reach -- docker forwards to the container's external interface, so the
# published :8000 answers nothing and the site looks dead from the host browser.
# (VS Code's own forwarding does reach loopback, so this only bites when the
# published port is used, which is exactly what docker-compose.yml declares.)
sed -i 's|^web: bench serve .*|web: bench serve --host 0.0.0.0 --port 8000|' ./Procfile

step "Site $SITE"
if [[ ! -d "sites/$SITE" ]]; then
    # --force because the mariadb volume outlives a wiped bench. Without
    # sites/$SITE the leftover database is unreadable anyway -- its password and
    # encryption key lived in that directory's site_config.json -- so it has to
    # be replaced, not preserved. Otherwise bench aborts on "database already
    # exists" and you get a bench with no site, which is the state this script
    # exists to prevent.
    bench new-site "$SITE" \
        --force \
        --mariadb-root-password 123 \
        --admin-password admin \
        --no-mariadb-socket
else
    echo "already exists, skipping"
fi

bench --site "$SITE" set-config developer_mode 1
bench --site "$SITE" clear-cache
bench use "$SITE"

# Link the app rather than fetching it. `bench get-app crm` clones frappe/crm --
# upstream, not this fork. Passing the local path instead (`bench get-app crm
# /workspace`, which is what CI does) treats it as an on-disk repo and git-clones
# it, giving apps/crm as a *second checkout*: edits in the editor would not reach
# the running site, which for a devcontainer is the whole point. A symlink keeps
# one tree -- and because the bench sits outside /workspace, the link does not
# fold the repo back into itself.
step "App"
[[ -e apps/crm ]] || ln -s "$REPO" apps/crm
./env/bin/pip install --quiet -e apps/crm
if ! grep -qxF crm sites/apps.txt 2>/dev/null; then
    # bench writes apps.txt with no trailing newline, so a bare `>>` splices the
    # names together into "frappecrm" and frappe.init then dies importing a
    # module by that name. Terminate the last line first.
    if [[ -s sites/apps.txt && -n "$(tail -c1 sites/apps.txt)" ]]; then
        echo >> sites/apps.txt
    fi
    echo crm >> sites/apps.txt
fi

if ! bench --site "$SITE" list-apps 2>/dev/null | grep -qw crm; then
    bench --site "$SITE" install-app crm
else
    echo "crm already installed on $SITE"
fi

# The symlink means bench never runs the `yarn install` that `bench get-app`
# would have. Without it there is no vite, no vitest and no eslint in here.
step "Frontend dependencies"
if [[ ! -d "$REPO/frontend/node_modules" ]]; then
    (cd "$REPO/frontend" && yarn install --frozen-lockfile)
else
    echo "node_modules present, skipping"
fi

step "Done"
# `yarn dev --host`, not a bare `yarn dev`: vite binds loopback by default, which
# the compose port publish cannot reach. VS Code's own forwarding reaches either,
# so --host is the form that works both ways.
cat <<EOF
bench:  $BENCH
site:   $SITE  (Administrator / admin)
start:  cd $BENCH && bench start               -> http://localhost:8000
front:  cd $REPO/frontend && yarn dev --host   -> http://localhost:8080
EOF
