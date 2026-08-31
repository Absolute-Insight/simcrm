---
name: dev-up
description: Bring up or verify the local Frappe dev environment (devcontainer bench + site + vite). Use when the user wants to start developing, when bench/yarn are missing, or when the dev site is not responding.
disable-model-invocation: true
---

# Start the dev environment

The toolchain lives in the `.devcontainer` stack, not on the host. Establish
where you are before running anything.

## 0. Where am I?

```bash
pwd            # host: /home/evo/dev/simcrm   container: /workspace/frappe-bench
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
(service `frappe`, workspace `/workspace/frappe-bench`). `postCreateCommand`
runs `scripts/init.sh`, which:

- `bench init` into `/workspace/frappe-bench`
- points mariadb/redis at the compose services
- `bench new-site dev.localhost` (root pw `123`, admin pw `admin`)
- `developer_mode 1`, `bench get-app crm`, `install-app crm`

It is **idempotent by design**: it exits early if `apps/frappe` already exists.
Do not re-run it by hand to "refresh" a bench — the early-exit guard is the only
thing standing between a rebuild and a second clone of the app over a symlink.

## 3. Inside the container

```bash
cd /workspace/frappe-bench
bench start                      # web :8000, socketio :9000
```

Frontend, in a second terminal:

```bash
cd /workspace/apps/crm/frontend  # or wherever the repo is mounted
yarn install
yarn dev                         # vite :8080
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
