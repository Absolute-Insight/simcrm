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

python3 - "$work/config.json" "$work" <<'PY'
import json
import re
import subprocess
import sys

services = json.load(open(sys.argv[1]))["services"]
work = sys.argv[2]
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
health = services["backup"].get("healthcheck", {}).get("test") or []
check(
	"backup has a healthcheck on the age of the newest dump",
	bool(health) and "private/backups" in health[-1] and "-mmin" in health[-1],
	str(health),
)
offsite_health = services["backup-offsite"]["healthcheck"]["test"][-1]
check("backup-offsite's healthcheck asks how old the newest copy is", "--max-age" in offsite_health)

# infra-1: the encryption key does not go off-host in plaintext by default.
offsite = script("backup-offsite")
check(
	"backup-offsite excludes site_config_backup.json by default",
	'set -- --exclude "*site_config_backup*"' in offsite,
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

print()
if failures:
	print(f"{failures} deploy/docker-compose.yml check(s) failed")
	sys.exit(1)
print("all deploy/docker-compose.yml checks passed")
PY
