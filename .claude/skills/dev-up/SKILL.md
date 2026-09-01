---
name: dev-up
description: Bring up or verify the local Frappe dev environment (devcontainer bench + site + vite). Use when the user wants to start developing, when bench/yarn are missing, or when the dev site is not responding.
---

# Start the dev environment

The toolchain lives in the `.devcontainer` stack, not on the host. Establish
where you are before running anything.

## 0. Where am I?

```bash
pwd            # host: /home/evo/dev/simcrm   container: /workspace
command -v bench yarn
```

If `bench` is missing you are on the host. The host cannot run bench — say so
and go to step 1 rather than trying to install it.

## 1. Host-side prerequisite check

```bash
ls -l /var/run/docker.sock     # must be a SOCKET (srw-...), not a directory
docker ps                      # daemon reachable
```

A **directory** at that path means compose created it because the daemon socket
was elsewhere; every docker command inside the container will then fail with a
confusing error. Fix that before opening the container.

## 2. Open the devcontainer

This is the user's action, not yours — VS Code → *Reopen in Container*
(service `frappe`, workspace `/workspace`, which is the repo). `postCreateCommand`
runs `scripts/init.sh`, which:

- `bench init` into `/home/frappe/frappe-bench`, a named docker volume, against
  the frappe commit pinned in `scripts/frappe-pin.env`
- points mariadb/redis at the compose services
- `bench new-site dev.localhost` (root pw `123`, admin pw `admin`)
- `developer_mode 1`, symlinks `apps/crm` → `/workspace`, `install-app crm`
- `yarn install` in `frontend/`

The bench is deliberately **not** in the repo: that keeps it out of `git status`,
stops `apps/crm` folding `/workspace` back into itself, and lets it outlive a
container rebuild.

Every step is guarded, so **re-running it is the repair**:

```bash
bash /workspace/scripts/init.sh
```

It resumes rather than starting over, and is a no-op against a finished bench.
It tees to `.devcontainer/init.log` — read that first when the container comes up
and nothing works, because postCreate output scrolls away in the Dev Containers
terminal and a failure there is otherwise invisible.

## 3. Inside the container

```bash
cd /home/frappe/frappe-bench
bench start                      # web :8000, socketio :9000
```

Frontend, in a second terminal:

```bash
cd /workspace/frontend           # init.sh has already run yarn install
yarn dev --host                  # vite :8080 -- --host, or the published port
                                 # cannot reach it (vite binds loopback)
```

## 4. Verify, don't assume

```bash
bench --site dev.localhost doctor
```

`Scheduler disabled ... True` means the cron jobs in `crm/hooks.py` — hourly
signals, deal-health scoring, the daily digest — are silently not running, with
nothing in any log to say so. Fix with
`bench --site dev.localhost enable-scheduler`.

## Do not develop against the test site

`test_site` is for `bench run-tests` and gets reinstalled. `dev.localhost` is
the one you browse. Mixing them puts demo records into the suite's fixtures —
see `/test`.
