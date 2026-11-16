#!/usr/bin/env bash
# Static checks on deploy/docker-compose.yml: properties that are easy to lose
# in an edit and that nothing else would notice until a production host did.
#
#   bash .github/helper/test-deploy-compose.sh
#
# Starts nothing. `docker compose config` resolves the file with only the
# required keys set, and everything below reads that. The scripts embedded in
# the file are syntax-checked too: they are strings in YAML, so no linter sees
# them, and the first shell to parse one is otherwise a container on a host.
#
# The backup scripts are also RUN, hermetically: the embedded `backup` and
# `backup-offsite` loops, scripts/restore-drill.sh and
# scripts/purge-plaintext-site-config-backups.sh execute against shims for
# docker, rclone, curl, wget, bench, date and sleep in a temp directory. No
# container, bucket or network is touched.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="$here/../../deploy/docker-compose.yml"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cat >"$work/minimal.env" <<'EOF'
VECTORA_IMAGE=ghcr.io/absolute-insight/simcrm
VECTORA_TAG=stable
SITE_NAME=smoke.localhost
DB_ROOT_PASSWORD=smoke-root-pw
ADMIN_PASSWORD=smoke-admin-pw
EOF

if ! docker compose -f "$compose" --env-file "$work/minimal.env" \
	--profile offsite --profile local-model --profile gpu-model \
	config --format json >"$work/config.json"; then
	echo "FAIL  deploy/docker-compose.yml does not parse"
	exit 1
fi

# .env.example must parse too, once its blanks are filled: it is what a new
# operator starts from, and every key it names must be one the file reads.
sed -e 's/^\(DB_ROOT_PASSWORD\|ADMIN_PASSWORD\|OFFSITE_[A-Z_]*\)=$/\1=dummy/' \
	-e 's/^#\(B2_ACCOUNT_ID\|B2_APPLICATION_KEY\|OFFSITE_[A-Z_]*\|BACKUP_[A-Z_]*\)=.*/\1=dummy/' \
	"$here/../../deploy/.env.example" >"$work/example.env"
if ! docker compose -f "$compose" --env-file "$work/example.env" --profile offsite config -q; then
	echo "FAIL  deploy/docker-compose.yml does not parse with a filled-in .env.example"
	exit 1
fi

python3 - "$work/config.json" "$work" "$here/../.." <<'PY'
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

services = json.load(open(sys.argv[1]))["services"]
work = sys.argv[2]
repo = os.path.abspath(sys.argv[3])
failures = 0


def check(name, ok, detail=""):
	global failures
	if ok:
		print(f"ok    {name}")
	else:
		failures += 1
		print(f"FAIL  {name}" + (f": {detail}" if detail else ""))


def size(text):
	"""'384M', '192mb', '1073741824' -> bytes."""
	m = re.fullmatch(r"(\d+)\s*([kmg]?)b?", str(text).strip().lower())
	if not m:
		raise ValueError(f"not a size: {text!r}")
	return int(m.group(1)) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2)]


def limit(service):
	return size(services[service]["deploy"]["resources"]["limits"]["memory"])


def script(service, key="command"):
	"""An embedded script, with compose's `$$` escaping undone."""
	value = services[service]
	for part in key.split("."):
		value = value[part]
	return value[-1].replace("$$", "$")


# seam_perf_n13-5: InnoDB sized, and sized inside the container.
db = services["db"]["command"]
pool = [a.split("=", 1)[1] for a in db if a.startswith("--innodb-buffer-pool-size=")]
check("db sets an InnoDB buffer pool size", len(pool) == 1, str(db))
if pool:
	share = size(pool[0]) / limit("db")
	check(
		"the default buffer pool is at most 60% of the db memory limit",
		share <= 0.6,
		f"{pool[0]} is {share:.0%} of the limit",
	)

# infra-9, and why it is NOT fixed the obvious way. redis-cache also holds
# keys that must outlive memory pressure and restarts: the Acumatica in-flight
# markers that stop a retried quote being written to the ERP twice, and the
# event-reminder ledger. So it must neither evict nor stop persisting, and a
# well-meant "it is only a cache" edit has to fail here. Redis's defaults are
# noeviction and RDB snapshots, so the safe states are: no flag at all, or the
# flag set to exactly that.
cache = " ".join(str(a) for a in services["redis-cache"].get("command") or []).lower()
policy = re.search(r"--maxmemory-policy[ =]+(\S+)", cache)
check(
	"redis-cache never evicts (no maxmemory-policy, or noeviction)",
	policy is None or policy.group(1) == "noeviction",
	cache,
)
check(
	"redis-cache keeps its snapshots (no --save override, RDB not disabled)",
	"--save" not in cache and "--appendonly no" not in cache and ".conf" not in cache,
	cache,
)
queue = " ".join(services["redis-queue"].get("command") or [])
check("redis-queue has no maxmemory and no eviction policy", "maxmemory" not in queue, queue)
check("redis-queue is append-only", "--appendonly yes" in queue, queue)

# infra-2: a stale backup is a visible state.
health = [a.replace("$$", "$") for a in services["backup"].get("healthcheck", {}).get("test") or []]
check(
	"backup has a healthcheck on the age of the newest dump",
	bool(health) and "private/backups" in health[-1] and "-mmin" in health[-1],
	str(health),
)
if health:
	for value, want in (("26", 0), ("26.5", 0), ("abc", 0), ("", 0), ("08", 0), ("00", 0)):
		# No dump exists in this throwaway directory, so a healthy parse is
		# "ran find, found nothing": exit 1 with nothing on stderr. A broken
		# expression is a shell error instead.
		result = subprocess.run(
			["sh", "-c", health[-1]],
			env={"PATH": "/usr/bin:/bin", "SITE_NAME": "none.invalid", "BACKUP_MAX_AGE_HOURS": value},
			capture_output=True,
			text=True,
		)
		check(
			f"the backup healthcheck survives BACKUP_MAX_AGE_HOURS={value!r}",
			result.returncode == 1 and not result.stderr.strip(),
			f"exit {result.returncode}: {result.stderr.strip()}",
		)
offsite_health = services["backup-offsite"]["healthcheck"]["test"][-1]
check("backup-offsite's healthcheck asks how old the newest copy is", "--max-age" in offsite_health)

# infra-1: the encryption key does not go off-host in plaintext by default.
offsite = script("backup-offsite")
check(
	"backup-offsite excludes site_config_backup.json by default",
	'set -- --filter "- *site_config_backup*"' in offsite,
)
copies = [line for line in offsite.splitlines() if "rclone copy" in line and not line.lstrip().startswith("#")]
check(
	"every rclone copy carries the filter",
	bool(copies) and all('"$@"' in line for line in copies),
	str(copies),
)
env = services["backup-offsite"]["environment"]
check("offsite encryption is off unless asked for", env.get("OFFSITE_CRYPT_PASSWORD") == "")
check("offsite site_config copying is off unless asked for", env.get("OFFSITE_INCLUDE_SITE_CONFIG") == "0")
# infra-10: nothing is deleted at the destination unless asked for.
check("offsite pruning is off unless asked for", env.get("OFFSITE_RETENTION_DAYS") == "0")

# infra-3: "the directory exists" is not "the site exists".
create = script("create-site")
check(
	"create-site does not take a bare directory for a site",
	not re.search(r'if \[ -d "sites/[^"]*" \]; then\s*\n\s*echo "Site', create),
)
check("create-site marks an unfinished create", ".creating-" in create)
# A partial site is removed on evidence, never on a check that did not answer.
check(
	"create-site asks the database before it removes anything",
	"db_verdict" in create and "information_schema.tables" in create,
)
removals = [m.start() for m in re.finditer(r'rm -rf "sites/', create)]
guard = create.find("absent|partial)")
stop = create.find("*)", guard)
check(
	"the only site removal is under a database verdict of absent or partial",
	len(removals) == 1 and guard != -1 and guard < removals[0] < stop,
	f"{len(removals)} removal(s)",
)
check("an unanswered check deletes nothing", "echo unknown" in create and "list-apps 2>/dev/null" not in create)
check("the root password is not in the mariadb client's argv", "--password" not in create.split("bench new-site")[0] and "-p$" not in create)
# infra-13
check("create-site can set host_name", "set-config host_name" in create)
check(
	"host_name is opt-in",
	services["create-site"]["environment"].get("SITE_HOST_NAME") == "",
)

# infra-8: the images this stack depends on cannot move under it.
for name in ("db", "redis-cache", "redis-queue", "backup-offsite"):
	check(f"{name} is pinned by digest", "@sha256:" in services[name]["image"], services[name]["image"])

# Every embedded script parses in the shell that will run it.
for service, key, shell in (
	("configurator", "command", "bash"),
	("create-site", "command", "bash"),
	("backup", "command", "bash"),
	("backup", "healthcheck.test", "sh"),
	("backup-offsite", "command", "sh"),
	("backup-offsite", "healthcheck.test", "sh"),
	("scheduler", "healthcheck.test", "sh"),
	("ollama-pull", "command", "sh"),
	("llm-fetch", "command", "sh"),
):
	path = f"{work}/{service}-{key}.sh"
	with open(path, "w") as f:
		f.write(script(service, key))
	result = subprocess.run([shell, "-n", path], capture_output=True, text=True)
	check(f"{service} {key} parses as {shell}", result.returncode == 0, result.stderr.strip())

# --- .env.example names only keys the file reads ---------------------------------
compose_text = open(f"{repo}/deploy/docker-compose.yml").read()
example_keys = sorted(
	set(re.findall(r"^#?([A-Z][A-Z0-9_]+)=", open(f"{repo}/deploy/.env.example").read(), re.M))
)
unread = [k for k in example_keys if "${" + k not in compose_text]
check(".env.example names no key docker-compose.yml ignores", not unread, str(unread))
example = open(f"{repo}/deploy/.env.example").read()
check(
	".env.example asks for OFFSITE_CRYPT_PASSWORD as a setting, not a comment",
	re.search(r"^OFFSITE_CRYPT_PASSWORD=$", example, re.M) is not None,
)

# --- Running the backup scripts against shims ---------------------------------------
# Every external command the scripts call is a small sh script here that logs
# its argv (one call per line, arguments separated by " | ") and answers from
# environment variables, so each test states the world it runs in.
shims = f"{work}/bin"
os.makedirs(shims, exist_ok=True)
SHIMS = {
	"rclone": r"""#!/bin/sh
for a in "$@"; do printf '%s | ' "$a"; done >> "$SHIM_LOG/rclone.log"; echo >> "$SHIM_LOG/rclone.log"
cmd="$1"; shift
target=""
for a in "$@"; do case "$a" in *:*) target="$a"; break ;; esac; done
case "$cmd" in
  obscure) cat >/dev/null; echo OBSCURED ;;
  config)
    case "$1" in
      file) echo "Configuration file is stored at:"; echo "$SHIM_STATE/rclone.conf" ;;
      show) printf '%s\n' "${RCLONE_CONFIG_SHOW:-}"; [ -n "${RCLONE_CONFIG_SHOW:-}" ] || exit 1 ;;
    esac ;;
  lsd) exit "${RCLONE_LSD_RC:-0}" ;;
  cat)
    case "$target" in
      hcping:*)
        printf 'rclone-http: %s%s\n' "$RCLONE_CONFIG_HCPING_URL" "${target#hcping:}" >> "$SHIM_LOG/ping.log"
        exit "${PING_RC:-0}" ;;
      *.vectora-canary)
        if [ "${RCLONE_CANARY:-}" = bad ]; then echo "failed to authenticate decrypted block - bad password?" >&2; exit 1; fi
        f="$SHIM_STATE/canary-${target%%:*}"
        if [ -e "$f" ]; then cat "$f"; exit 0; fi
        echo "ERROR : .vectora-canary: object not found" >&2; exit 4 ;;
      *)
        if [ "${RCLONE_CANARY:-}" = bad ]; then echo "failed to authenticate decrypted block - bad password?" >&2; exit 1; fi
        exit 0 ;;
    esac ;;
  rcat) cat > "$SHIM_STATE/canary-${target%%:*}"; exit 0 ;;
  copy)
    dest="$2"
    case "$dest" in
      *monthly*)
        for a in "$@"; do
          case "$a" in "+ "*) stamp=$(printf '%s' "$a" | cut -c3-17); m=$(printf '%s' "$stamp" | cut -c1-6); echo "$stamp" > "$SHIM_STATE/monthly-$m" ;; esac
        done
        n=$(( $(cat "$SHIM_STATE/monthly-copies" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$SHIM_STATE/monthly-copies"
        if [ "$n" -le "${RCLONE_MONTHLY_FAILS:-0}" ]; then exit 1; fi ;;
    esac
    exit "${RCLONE_COPY_RC:-0}" ;;
  lsf)
    dest="$1"
    case "$dest" in
      *monthly*)
        for a in "$@"; do
          case "$a" in [0-9][0-9][0-9][0-9][0-9][0-9]'*-database*')
            m=$(printf '%s' "$a" | cut -c1-6)
            if [ -e "$SHIM_STATE/monthly-$m" ]; then echo "$(cat "$SHIM_STATE/monthly-$m")-s-database.sql.gz"; exit 0; fi ;;
          esac
        done
        exit "${RCLONE_LSF_MONTHLY_RC:-3}" ;;
      *)
        if [ -e "$SHIM_STATE/deleted" ]; then
          case " $* " in *" --b2-versions "*) [ "${RCLONE_VERSIONS_SURVIVE:-0}" = 1 ] && printf '%s\n' "${RCLONE_LSF_DAILY}" ;; esac
          exit 0
        fi
        printf '%s\n' "${RCLONE_LSF_DAILY-20261116_020000-s-database.sql.gz}" | grep . ; exit 0 ;;
    esac ;;
  delete)
    [ -z "${RCLONE_DELETE_ERR:-}" ] || echo "$RCLONE_DELETE_ERR" >&2
    [ "${RCLONE_DELETE_RC:-0}" != 0 ] || : > "$SHIM_STATE/deleted"
    exit "${RCLONE_DELETE_RC:-0}" ;;
  *) exit 0 ;;
esac
""",
	"curl": r"""#!/bin/sh
printf 'argv: %s\n' "$*" >> "$SHIM_LOG/ping.log"
printf 'stdin: %s\n' "$(cat)" >> "$SHIM_LOG/ping.log"
exit "${PING_RC:-0}"
""",
	"wget": r"""#!/bin/sh
printf 'argv: %s\n' "$*" >> "$SHIM_LOG/ping.log"
exit "${PING_RC:-0}"
""",
	"bench": r"""#!/bin/sh
printf '%s\n' "$*" >> "$SHIM_LOG/bench.log"
exit "${BENCH_RC:-0}"
""",
	# The loops never end on their own: the Nth sleep ends the script.
	"sleep": r"""#!/bin/sh
n=$(( $(cat "$SHIM_STATE/sleeps" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$SHIM_STATE/sleeps"
if [ "$n" -ge "${SLEEP_LIMIT:-1}" ]; then kill -TERM "$PPID"; fi
exit 0
""",
	"date": r"""#!/bin/sh
if [ "$1" = "+%Y%m" ] && [ -n "${FAKE_MONTH:-}" ]; then echo "$FAKE_MONTH"; exit 0; fi
exec REALDATE "$@"
""".replace("REALDATE", shutil.which("date")),
	"docker": r"""#!/bin/sh
printf '%s\n' "$*" >> "$SHIM_LOG/docker.log"
case "$*" in
  "compose version"*) exit 0 ;;
  "ps -aq"*) printf '%s' "${DOCKER_PS_OUT:-}" ; exit 0 ;;
esac
exit 0
""",
}
for name, body in SHIMS.items():
	path = f"{shims}/{name}"
	with open(path, "w") as f:
		f.write(body)
	os.chmod(path, 0o755)


def fresh(name):
	"""A clean log/state/sites tree for one scenario."""
	root = f"{work}/run-{name}"
	shutil.rmtree(root, ignore_errors=True)
	for d in ("log", "state", "sites/s.example/private/backups"):
		os.makedirs(f"{root}/{d}")
	return root


def backup_set(root, stamp, age_minutes=120):
	"""Write one nightly set, `age_minutes` old."""
	d = f"{root}/sites/s.example/private/backups"
	when = time.time() - age_minutes * 60
	for suffix in ("database.sql.gz", "files.tar", "private-files.tar", "site_config_backup.json"):
		p = f"{d}/{stamp}-s_example-{suffix}"
		open(p, "w").write("x")
		os.utime(p, (when, when))


def run_script(root, text, shell, env, sleeps=1):
	"""Run an embedded loop, rewritten to use this tree instead of a container's paths."""
	text = (
		text.replace("/data/sites", f"{root}/sites")
		.replace("/home/frappe/frappe-bench/sites", f"{root}/sites")
		.replace("/tmp/offsite.", f"{root}/state/offsite.")
	)
	path = f"{root}/script.sh"
	open(path, "w").write(text)
	full = {
		"PATH": f"{shims}:/usr/bin:/bin",
		"SHIM_LOG": f"{root}/log",
		"SHIM_STATE": f"{root}/state",
		"SLEEP_LIMIT": str(sleeps),
		"SITE_NAME": "s.example",
		"HOME": root,
	}
	full.update(env)
	result = subprocess.run([shell, path], env=full, capture_output=True, text=True, timeout=120)
	return result.stdout + result.stderr


def log(root, name):
	try:
		return open(f"{root}/log/{name}.log").read()
	except FileNotFoundError:
		return ""


def lines(root, name, needle):
	return [line for line in log(root, name).splitlines() if needle in line]


def calls(root, cmd):
	"""Every rclone call of one subcommand, as its argument list."""
	out = []
	for line in log(root, "rclone").splitlines():
		args = line.rstrip(" |").split(" | ")
		if args and args[0] == cmd:
			out.append(args)
	return out


OFFSITE_ENV = {
	"RCLONE_CONFIG_OFFSITE_ACCOUNT": "acct",
	"RCLONE_CONFIG_OFFSITE_KEY": "key",
	"BACKUP_TARGET": "offsite:bucket",
	"OFFSITE_CRYPT_PASSWORD": "",
	"OFFSITE_CRYPT_SALT": "",
	"OFFSITE_ALLOW_PLAINTEXT": "0",
	"OFFSITE_INCLUDE_SITE_CONFIG": "0",
	"OFFSITE_RETENTION_DAYS": "0",
	"OFFSITE_MAX_AGE_HOURS": "28",
	"OFFSITE_PING_URL": "",
	"FAKE_MONTH": "202611",  # the sets backup_set() writes; CI runs in every month
}
offsite_cmd = script("backup-offsite")
offsite_hc = script("backup-offsite", "healthcheck.test")
backup_cmd = script("backup")
backup_hc = script("backup", "healthcheck.test")
SECRET = "0f1e2d3c-secret-path-4b5a"


def offsite(name, sleeps=1, **env):
	root = fresh(name)
	backup_set(root, "20261102_020000")
	backup_set(root, "20261103_020000")
	return root, run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, **env}, sleeps)


# The backup healthcheck can pass at all (it could not: `find"/home...`).
root = fresh("backup-health")
backup_set(root, "20261116_020000", age_minutes=60)
hc = backup_hc.replace("/home/frappe/frappe-bench/sites", f"{root}/sites")
fresh_ok = subprocess.run(["sh", "-c", hc], env={"PATH": "/usr/bin:/bin", "SITE_NAME": "s.example"}).returncode
root2 = fresh("backup-health-stale")
backup_set(root2, "20261114_020000", age_minutes=30 * 60)
hc2 = backup_hc.replace("/home/frappe/frappe-bench/sites", f"{root2}/sites")
stale = subprocess.run(["sh", "-c", hc2], env={"PATH": "/usr/bin:/bin", "SITE_NAME": "s.example"}).returncode
check("the backup healthcheck passes on a dump an hour old", fresh_ok == 0, f"exit {fresh_ok}")
check("the backup healthcheck fails on a dump 30 hours old", stale == 1, f"exit {stale}")

# 1. Retention unset: not one delete, whatever else happens.
root, out = offsite("no-retention", sleeps=3)
check("offsite with OFFSITE_RETENTION_DAYS unset issues no delete", not calls(root, "delete"), log(root, "rclone"))
check("... and copies every hour", len(calls(root, "copy")) >= 3, out)
root, out = offsite("bad-retention", OFFSITE_RETENTION_DAYS="7")
check("a retention under 14 days deletes nothing", not calls(root, "delete"), out)

# 2. A no-delete key with retention set: delegated, said once, not a failure.
root, out = offsite(
	"no-delete-key",
	sleeps=2,
	OFFSITE_RETENTION_DAYS="30",
	RCLONE_DELETE_RC="1",
	RCLONE_DELETE_ERR="ERROR : 20261001_020000-s-database.sql.gz: Couldn't delete: unauthorized: (401 unauthorized)",
	OFFSITE_PING_URL=f"https://hc.example/{SECRET}",
)
status = open(f"{root}/state/offsite.status").read()
check("a key that may not delete: pruning is reported as delegated", "delegated to the bucket's lifecycle rules" in out, out)
check("... and recorded in the status file", "prune=delegated" in status, status)
check("... and not retried every hour", len(calls(root, "delete")) == 1, log(root, "rclone"))
check("... and not pinged as a failure", "/fail" not in log(root, "ping"), log(root, "ping"))
root, out = offsite("prune-error", OFFSITE_RETENTION_DAYS="30", RCLONE_DELETE_RC="1", RCLONE_DELETE_ERR="connection reset by peer", OFFSITE_PING_URL=f"https://hc.example/{SECRET}")
check("any other prune error is a failure, pinged as one", "PRUNE FAILED" in out and f"{SECRET}/fail" in log(root, "ping"), out)

# 3. No passphrase: still copies, warns every run, and the healthcheck says so.
root, out = offsite("plaintext", sleeps=2)
status = open(f"{root}/state/offsite.status").read()
check("unencrypted copies still run", len(calls(root, "copy")) >= 2, out)
check("... with a warning on every run", out.count("WARNING: copies leave this host UNENCRYPTED") == 2, out)
check("... and encryption=off in the status file", "encryption=off" in status, status)
check("... to the same plaintext prefix as before", any(a[2] == "offsite:bucket/s.example" for a in calls(root, "copy")), log(root, "rclone"))
check(
	"... and no new plaintext monthly tier (an upgraded stack keeps doing what it did)",
	not [a for a in calls(root, "copy") if "monthly" in a[2]] and "monthly=off" in status,
	log(root, "rclone"),
)
hc_env = {**OFFSITE_ENV, "PATH": f"{shims}:/usr/bin:/bin", "SHIM_LOG": f"{root}/log", "SHIM_STATE": f"{root}/state", "SITE_NAME": "s.example"}
hc_text = offsite_hc.replace("/data/sites", f"{root}/sites").replace("/tmp/offsite.", f"{root}/state/offsite.")
r = subprocess.run(["sh", "-c", hc_text], env=hc_env, capture_output=True, text=True)
check("the offsite healthcheck reports unencrypted copies", r.returncode == 1 and "NOT encrypted" in r.stdout, r.stdout)
r = subprocess.run(["sh", "-c", hc_text], env={**hc_env, "OFFSITE_ALLOW_PLAINTEXT": "1"}, capture_output=True, text=True)
check("... until plaintext is accepted with OFFSITE_ALLOW_PLAINTEXT=1", r.returncode == 0, r.stdout)
r = subprocess.run(["sh", "-c", hc_text], env={**hc_env, "RCLONE_LSF_DAILY": ""}, capture_output=True, text=True)
check("the offsite healthcheck still fails on a stale destination", r.returncode == 1 and "no database dump newer" in r.stdout, r.stdout)

root, out = offsite("encrypted", FAKE_MONTH="202611", OFFSITE_CRYPT_PASSWORD="correct horse", OFFSITE_CRYPT_SALT="battery")
conf = open(f"{root}/state/rclone.conf").read()
status = open(f"{root}/state/offsite.status").read()
check("with a passphrase: no plaintext warning", "UNENCRYPTED" not in out, out)
check("... encryption=on in the status file", "encryption=on" in status, status)
check("... the monthly tier runs, through its own crypt remote", any(a[2] == "offsitecryptmonthly:" for a in calls(root, "copy")), log(root, "rclone"))
check(
	"... dailies and monthlies go to their own .crypt prefixes",
	"remote = offsite:bucket/s.example.crypt" in conf and "remote = offsite:bucket/monthly/s.example.crypt" in conf,
	conf,
)
check("... the passphrase never reaches a command line", "correct horse" not in log(root, "rclone") and "battery" not in log(root, "rclone"))
r = subprocess.run(["sh", "-c", hc_text.replace(f"run-plaintext", "run-encrypted")], env={**hc_env, "SHIM_STATE": f"{root}/state", "OFFSITE_CRYPT_PASSWORD": "x"}, capture_output=True, text=True)
check("... and the healthcheck is green", r.returncode == 0, r.stdout)
canaries = [f"{root}/state/canary-offsitecrypt", f"{root}/state/canary-offsitecryptmonthly"]
check(
	"... a passphrase canary is written to both crypt prefixes",
	all(os.path.exists(c) and "vectora offsite canary" in open(c).read() for c in canaries) and "wrote and verified the passphrase canary" in out,
	out,
)
# Restart with the same passphrase: the canary reads back, nothing is rewritten.
open(f"{root}/log/rclone.log", "w").close()
os.remove(f"{root}/state/sleeps")
out = run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, "OFFSITE_CRYPT_PASSWORD": "correct horse"}, 1)
check("... a restart with the same passphrase reads the canary and goes on", not calls(root, "rcat") and calls(root, "copy"), out)
# A canary that decrypts to something else: refuse, copy nothing, ping /fail.
open(canaries[0], "w").write("garbage")
open(f"{root}/log/rclone.log", "w").close()
os.remove(f"{root}/state/sleeps")
out = run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, "OFFSITE_CRYPT_PASSWORD": "typo", "OFFSITE_PING_URL": f"https://hc.example/{SECRET}"}, 1)
check("a canary that does not match: refuses to start and copies nothing", "refusing to start" in out and not calls(root, "copy"), out)
check("... and pings /fail", f"{SECRET}/fail" in log(root, "ping"), log(root, "ping"))
root, out = offsite("canary-bad-key", OFFSITE_CRYPT_PASSWORD="typo", RCLONE_CANARY="bad")
check("a passphrase that cannot decrypt the prefix: refuses to start, copies nothing", "refusing to start" in out and not calls(root, "copy") and not calls(root, "rcat"), out)
check("pruning never deletes the canary", "--exclude .vectora-canary" in offsite_cmd)

# 4. Pings: start, success, failure, and the secret path never logged.
root, out = offsite("ping-ok", OFFSITE_PING_URL=f"https://hc.example/ping/{SECRET}/")
pings = log(root, "ping")
check("offsite pings /start then success", f'{SECRET}/start"' in pings and f'{SECRET}"' in pings, pings)
check("... and logs the ping URL only up to its host", SECRET not in out and "https://hc.example/..." in out, out)
root, out = offsite("ping-fail", OFFSITE_PING_URL=f"https://hc.example/{SECRET}", RCLONE_COPY_RC="1")
check("a failed copy pings /fail", f"{SECRET}/fail" in log(root, "ping"), log(root, "ping"))
root, out = offsite("ping-down", OFFSITE_PING_URL=f"https://hc.example/{SECRET}", PING_RC="7")
check("an unreachable monitor costs nothing", "did not get through (ignored)" in out and calls(root, "copy"), out)
check("... and its URL is still not logged", SECRET not in out, out)
root, out = offsite("ping-off")
check("no OFFSITE_PING_URL, no pings", log(root, "ping") == "", log(root, "ping"))
root, out = offsite("ping-bad", OFFSITE_PING_URL=f"ftp://hc.example/{SECRET}")
check("a URL that is not http(s) is refused, not pinged", log(root, "ping") == "" and "pings are off" in out, out)

root = fresh("backup-ping")
env = {"BACKUP_HOUR": "2", "BACKUP_MAX_AGE_HOURS": "26", "BACKUP_PING_URL": f"https://hc.example/{SECRET}"}
out = run_script(root, backup_cmd, "bash", env, sleeps=2)
pings = log(root, "ping")
check("backup pings /start and success around a good run", f'{SECRET}/start"' in pings and f'{SECRET}"' in pings, pings)
check("... with the URL on curl's stdin, not in its argv", all(SECRET not in line for line in lines(root, "ping", "argv:")), pings)
check("... and not in the log", SECRET not in out and "https://hc.example/..." in out, out)
root = fresh("backup-ping-fail")
out = run_script(root, backup_cmd, "bash", {**env, "BENCH_RC": "1"}, sleeps=2)
check("a failed backup pings /fail", f'{SECRET}/fail"' in log(root, "ping"), log(root, "ping"))
root = fresh("backup-ping-down")
out = run_script(root, backup_cmd, "bash", {**env, "PING_RC": "28"}, sleeps=2)
check("an unreachable monitor does not stop the backup", "did not get through (ignored)" in out and log(root, "bench"), out)
root = fresh("backup-no-ping")
out = run_script(root, backup_cmd, "bash", {**env, "BACKUP_PING_URL": ""}, sleeps=2)
check("no BACKUP_PING_URL, no pings", log(root, "ping") == "" and log(root, "bench"), out)
check("pings are bounded in time", "timeout 15 curl" in backup_cmd and "-m 10" in backup_cmd and "timeout 15 rclone cat" in offsite_cmd)
check(
	"no ping URL is ever put on a command line (no wget fallback)",
	not [l for l in offsite_cmd.splitlines() if "wget" in l and not l.lstrip().startswith("#")],
)
# The rclone image has no curl: pings go through rclone's http backend, with
# the URL in the environment.
root = fresh("ping-rclone")
backup_set(root, "20261102_020000")
nocurl = offsite_cmd.replace("command -v curl", "false")
out = run_script(root, nocurl, "sh", {**OFFSITE_ENV, "OFFSITE_PING_URL": f"https://hc.example/{SECRET}"}, 1)
pings = log(root, "ping")
check(
	"without curl, offsite pings /start and /0 through rclone's http backend",
	f"rclone-http: https://hc.example/{SECRET}/start" in pings and f"rclone-http: https://hc.example/{SECRET}/0" in pings,
	pings,
)
check("... with the URL only in the environment, never in rclone's argv", SECRET not in log(root, "rclone") and SECRET not in out, log(root, "rclone"))
root = fresh("ping-rclone-fail")
backup_set(root, "20261102_020000")
out = run_script(root, nocurl, "sh", {**OFFSITE_ENV, "OFFSITE_PING_URL": f"https://hc.example/{SECRET}", "RCLONE_COPY_RC": "1"}, 1)
check("... and /fail on a failed run", f"rclone-http: https://hc.example/{SECRET}/fail" in log(root, "ping"), log(root, "ping"))


# 5. The monthly tier: the month's first set, once.
def monthly_copies(root):
	return [" | ".join(a) for a in calls(root, "copy") if "/monthly/" in a[2]]


MONTHLY = {"OFFSITE_ALLOW_PLAINTEXT": "1"}  # plain paths are easier to read in a failure
root, out = offsite("monthly", sleeps=3, FAKE_MONTH="202611", **MONTHLY)
copies = monthly_copies(root)
check("the first set of the month is copied to monthly/ once in three runs", len(copies) == 1, str(copies))
check("... and it is the first set", copies and "+ 20261102_020000-*" in copies[0], str(copies))
check("... without site_config_backup.json", copies and "- *site_config_backup*" in copies[0], str(copies))
# A restart in the same month asks the destination, finds that set, and
# re-runs the copy of THAT set (rclone skips what is there) -- never another.
os.remove(f"{root}/state/sleeps")
open(f"{root}/log/rclone.log", "w").close()
run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, **MONTHLY, "FAKE_MONTH": "202611"}, 2)
copies = monthly_copies(root)
check("... and after a restart only that same set, once", len(copies) == 1 and "+ 20261102_020000-*" in copies[0], str(copies))
backup_set(root, "20261201_020000")
os.remove(f"{root}/state/sleeps")
open(f"{root}/log/rclone.log", "w").close()
run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, **MONTHLY, "FAKE_MONTH": "202612"}, 1)
copies = monthly_copies(root)
check("a new month gets its own copy", len(copies) == 1 and "+ 20261201_020000-*" in copies[0], str(copies))
root = fresh("monthly-fresh")
backup_set(root, "20261116_020000", age_minutes=5)
run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, **MONTHLY, "FAKE_MONTH": "202611"}, 1)
check("a set still being written is not the monthly copy yet", not monthly_copies(root), log(root, "rclone"))
root, out = offsite("monthly-list-error", FAKE_MONTH="202611", RCLONE_LSF_MONTHLY_RC="1", **MONTHLY, OFFSITE_PING_URL=f"https://hc.example/{SECRET}")
check("a monthly listing that fails copies nothing and pings /fail", not monthly_copies(root) and f"{SECRET}/fail" in log(root, "ping"), out)
# The dump reached monthly/ but the copy failed before the tars: the next run
# completes the same set, and only a copy that exits 0 marks the month done.
root, out = offsite("monthly-partial", sleeps=3, RCLONE_MONTHLY_FAILS="1", **MONTHLY, OFFSITE_PING_URL=f"https://hc.example/{SECRET}")
copies = monthly_copies(root)
check(
	"a partial monthly copy is completed on the next run, same set, then left alone",
	len(copies) == 2 and all("+ 20261102_020000-*" in c for c in copies),
	str(copies),
)
check("... the failed run pinged /fail", f"{SECRET}/fail" in log(root, "ping"), log(root, "ping"))
root = fresh("monthly-gone")
backup_set(root, "20261103_020000")
os.makedirs(f"{root}/state", exist_ok=True)
open(f"{root}/state/monthly-202611", "w").write("20261101_020000\n")
run_script(root, offsite_cmd, "sh", {**OFFSITE_ENV, **MONTHLY}, 2)
check("a monthly set no longer on the host is left as it is, not replaced", not monthly_copies(root), log(root, "rclone"))


# 6. The restore drill will not go near production.
def drill(*args, env=None):
	root = fresh("drill")
	full = {"PATH": f"{shims}:/usr/bin:/bin", "SHIM_LOG": f"{root}/log", "SHIM_STATE": f"{root}/state", "HOME": root}
	full.update(env or {})
	r = subprocess.run(
		["bash", f"{repo}/scripts/restore-drill.sh", "--env-file", "/nonexistent", "--image", "img:tag", *args, f"{root}/sites"],
		env=full, capture_output=True, text=True, timeout=60,
	)
	return root, r


for name in ("vectora", "Vectora", "vectora-qa", "vectora_prod", "vectora2"):
	root, r = drill("--project", name)
	touched = [l for l in log(root, "docker").splitlines() if not l.startswith(("compose version", "ps "))]
	check(f"restore-drill refuses project {name!r}", r.returncode == 2 and "refusing" in r.stderr and not touched, r.stderr + log(root, "docker"))
root, r = drill("--project", "bk-drill-x", env={"DOCKER_PS_OUT": "abc123"})
check("restore-drill refuses a project that already has containers", r.returncode == 2 and "already has containers" in r.stderr, r.stderr)
root, r = drill(env={"COMPOSE_PROJECT_NAME": "vectora"})
check("restore-drill ignores COMPOSE_PROJECT_NAME", "-p vectora " not in log(root, "docker"), log(root, "docker"))
drill_text = open(f"{repo}/scripts/restore-drill.sh").read()
check("the drill's network is internal and publishes no port", "internal: true" in drill_text and "ports:" not in drill_text)
check("the drill tears down with down -v on exit", "trap cleanup EXIT" in drill_text and "down -v --remove-orphans" in drill_text)
rclone_runs = [l for l in drill_text.splitlines() if "docker run" in l and '"$rclone_image"' in l and "obscure" not in l]
check(
	"the drill only ever reads from the bucket (lsf, or copy into its temp dir)",
	len(rclone_runs) == 2 and "lsf \"$src\"" in rclone_runs[0] and "copy \"$src\" /out" in drill_text,
	str(rclone_runs),
)


# 7. The purge is a dry run unless told, and asks for the bucket by name.
def purge(*args, answer="", **env):
	root = fresh("purge")
	full = {"PATH": f"{shims}:/usr/bin:/bin", "SHIM_LOG": f"{root}/log", "SHIM_STATE": f"{root}/state", "HOME": root,
		"RCLONE_CONFIG_OFFSITE_TYPE": "b2", "RCLONE_LSF_DAILY": "s/20261001_020000-s-site_config_backup.json"}
	full.update(env)
	r = subprocess.run(
		["bash", f"{repo}/scripts/purge-plaintext-site-config-backups.sh", *args, "offsite:vecbucket"],
		env=full, input=answer, capture_output=True, text=True, timeout=60,
	)
	return root, r


root, r = purge()
check("purge is a dry run by default", r.returncode == 0 and "Dry run" in r.stdout and not calls(root, "delete"), r.stdout + r.stderr)
check("... that prints the count", "current versions): 1" in r.stdout, r.stdout)
root, r = purge("--delete", answer="wrong\n")
check("purge --delete with the wrong bucket name deletes nothing", r.returncode == 1 and not calls(root, "delete"), r.stdout)
root, r = purge("--delete", answer="vecbucket\n")
dels = [" | ".join(a) for a in calls(root, "delete")]
check(
	"purge --delete, confirmed, hard-deletes only plaintext site configs",
	len(dels) == 1 and "--b2-hard-delete" in dels[0] and "- *.crypt/**" in dels[0] and "+ *site_config_backup*.json" in dels[0],
	str(dels),
)
check("... and succeeds only once no version is left", r.returncode == 0 and "in any version" in r.stdout, r.stdout + r.stderr)
check("... having listed with --b2-versions afterwards", any("--b2-versions" in a for a in calls(root, "lsf")[-1:]), log(root, "rclone"))
root, r = purge("--delete", answer="vecbucket\n", RCLONE_VERSIONS_SURVIVE="1")
check("purge fails when an old version survives the delete", r.returncode == 1 and "still recoverable" in r.stderr, r.stdout + r.stderr)
# A remote defined only in rclone.conf: its type is read from there.
root, r = purge("--delete", answer="vecbucket\n", RCLONE_CONFIG_OFFSITE_TYPE="", RCLONE_CONFIG_SHOW="[offsite]\ntype = b2\naccount = x")
dels = [" | ".join(a) for a in calls(root, "delete")]
check("a b2 remote from rclone.conf is still hard-deleted", len(dels) == 1 and "--b2-hard-delete" in dels[0], str(dels) + r.stderr)
root, r = purge("--delete", answer="vecbucket\n", RCLONE_CONFIG_OFFSITE_TYPE="")
check("a remote whose type cannot be told: --delete refuses", r.returncode == 2 and "cannot tell what kind of store" in r.stderr and not calls(root, "delete"), r.stderr)
root, r = purge("--delete", answer="vecbucket\n", RCLONE_CONFIG_OFFSITE_TYPE="s3")
check("a non-b2 versioning store: --delete refuses", r.returncode == 2 and not calls(root, "delete"), r.stderr)

print()
if failures:
	print(f"{failures} deploy/docker-compose.yml check(s) failed")
	sys.exit(1)
print("all deploy/docker-compose.yml checks passed")
PY
