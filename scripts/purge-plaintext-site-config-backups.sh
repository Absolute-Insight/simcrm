#!/usr/bin/env bash
# Remove the plaintext *site_config_backup.json files that backup-offsite
# copied to the bucket before it learned to leave them behind.
#
#   scripts/purge-plaintext-site-config-backups.sh [--delete] <remote:bucket/path>
#
# e.g. scripts/purge-plaintext-site-config-backups.sh offsite:vecmbp
#
# Each of those files is a site's site_config.json verbatim: db_password and
# encryption_key in plaintext. deploy/README.md, "Cleaning up the plaintext
# secrets already in the bucket", is the runbook this belongs to -- read the
# access logs and rotate first, then run this.
#
# Dry run by default: lists what matches and prints counts, deletes nothing.
# With --delete it asks you to type the bucket name, then deletes those files
# permanently (on B2, --b2-hard-delete: a plain delete would only *hide* them,
# leaving every secret recoverable as an old version). It then lists again with
# --b2-versions and fails unless no version of any of them is left. --delete
# needs to KNOW the remote is B2 (from the environment, or the remote's `type`
# in rclone.conf), and refuses otherwise.
#
# Only `*site_config_backup*.json` outside any `*.crypt/` prefix is touched.
# The encrypted archive's copies (<site>.crypt/..., stored as ciphertext and
# named .json.bin) are what makes that archive self-contained, and are left.
#
# Credentials: the server's key should NOT be able to delete (README.md,
# "Immutable copies"), so use your own. Either export rclone's variables for
# the remote named in the target (RCLONE_CONFIG_OFFSITE_TYPE/ACCOUNT/KEY), or
# PURGE_B2_ACCOUNT_ID and PURGE_B2_APPLICATION_KEY for a B2 key with
# listFiles + deleteFiles on the bucket. Runs the rclone on PATH, or the image
# docker-compose.yml pins when there is none.
set -euo pipefail

die() {
	echo "purge: $*" >&2
	exit 2
}

delete=0
target=""
while [ $# -gt 0 ]; do
	case "$1" in
	--delete) delete=1; shift ;;
	-h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
	-*) die "unknown option $1" ;;
	*) [ -z "$target" ] || die "one target only"; target="$1"; shift ;;
	esac
done
[ -n "$target" ] || die "usage: $0 [--delete] <remote:bucket/path>"
case "$target" in
*:*/* | *:*) ;;
*) die "'$target' is not an rclone remote path (remote:bucket[/path])" ;;
esac
target="${target%/}"
remote="${target%%:*}"
path="${target#*:}"
bucket="${path%%/*}"
[ -n "$remote" ] && [ -n "$bucket" ] || die "'$target' names no bucket"

upper="$(printf '%s' "$remote" | tr '[:lower:]-' '[:upper:]_')"
var_type="RCLONE_CONFIG_${upper}_TYPE"
if [ -z "${!var_type:-}" ] && [ -n "${PURGE_B2_ACCOUNT_ID:-}" ]; then
	export "RCLONE_CONFIG_${upper}_TYPE=b2"
	export "RCLONE_CONFIG_${upper}_ACCOUNT=${PURGE_B2_ACCOUNT_ID}"
	export "RCLONE_CONFIG_${upper}_KEY=${PURGE_B2_APPLICATION_KEY:?set PURGE_B2_APPLICATION_KEY too}"
fi
rtype="${!var_type:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v rclone >/dev/null 2>&1; then
	rc() { rclone "$@"; }
else
	image="$(sed -n 's|^ *image: \(rclone/rclone:[^ ]*\) *$|\1|p' "$here/../deploy/docker-compose.yml" | head -n 1)"
	[ -n "$image" ] || die "no rclone on PATH and no rclone pin in deploy/docker-compose.yml"
	command -v docker >/dev/null 2>&1 || die "neither rclone nor docker is on PATH"
	# Names only: the values stay in this process's environment, not in argv.
	envs=()
	while IFS= read -r name; do envs+=(-e "$name"); done < <(env | sed -n "s/^\(RCLONE_[A-Z0-9_]*\)=.*/\1/p")
	rc() { docker run --rm "${envs[@]}" "$image" "$@"; }
fi

# What kind of store this is decides whether a delete is a delete. On B2 a
# plain delete only HIDES a file: the secret stays readable as an old version,
# and the run would still look clean. So the type must be known -- from the
# environment, or from the rclone.conf that defines the remote -- before
# anything is deleted.
if [ -z "$rtype" ]; then
	rtype="$(rc config show "$remote" 2>/dev/null | sed -n 's/^type *= *//p' | head -n 1)" || rtype=""
fi

filters=(--filter "- *.crypt/**" --filter "+ *site_config_backup*.json" --filter "- *")

list() {
	# list [extra flags]: every matching file under the target, one per line
	rc lsf -R --files-only "${filters[@]}" "$@" "$target"
}

echo "Target: $target (bucket '$bucket', remote type '${rtype:-UNKNOWN}')"
current="$(list)" || die "cannot list $target -- check the key and the path"
n_current=$(printf '%s' "$current" | grep -c . || true)
echo "Matching files (current versions): $n_current"
printf '%s\n' "$current" | grep . | head -n 20 | sed 's/^/  /' || true
[ "$n_current" -le 20 ] || echo "  ... and $((n_current - 20)) more"

n_versions=""
if [ "$rtype" = b2 ]; then
	versions="$(list --b2-versions)" || die "cannot list old versions under $target"
	n_versions=$(printf '%s' "$versions" | grep -c . || true)
	echo "Matching files including old and hidden versions: $n_versions"
fi

if [ "$delete" != 1 ]; then
	echo
	echo "Dry run: nothing deleted. Re-run with --delete to remove the $n_current file(s) above."
	exit 0
fi
case "$rtype" in
b2 | local) ;;
"")
	die "refusing to delete: cannot tell what kind of store '$remote' is (no RCLONE_CONFIG_${upper}_TYPE, and 'rclone config show $remote' says nothing). On B2 a delete without --b2-hard-delete only hides a file and keeps the secret as a version. Set PURGE_B2_ACCOUNT_ID/PURGE_B2_APPLICATION_KEY, or RCLONE_CONFIG_${upper}_TYPE." ;;
*)
	die "refusing to delete on a '$rtype' remote: this script can only prove the files are gone (old versions included) on b2. Delete them, and every old version, with the store's own tools." ;;
esac
if [ "$n_current" = 0 ] && [ "${n_versions:-0}" = 0 ]; then
	echo "Nothing to delete."
	exit 0
fi

echo
echo "This permanently deletes $n_current file(s) from bucket '$bucket'. There is no undo."
printf 'Type the bucket name to confirm: '
read -r answer || answer=""
if [ "$answer" != "$bucket" ]; then
	echo "Not confirmed ('$answer' is not '$bucket'); nothing deleted."
	exit 1
fi

extra=()
[ "$rtype" = b2 ] && extra=(--b2-hard-delete)
if ! rc delete "${filters[@]}" "${extra[@]}" "$target"; then
	echo "Delete reported errors -- a key without deleteFiles, or files under Object Lock retention. See above." >&2
fi

left="$(list)" || left=""
n_left=$(printf '%s' "$left" | grep -c . || true)
echo "Deleted: $((n_current - n_left)) of $n_current. Left (current versions): $n_left"
if [ "$rtype" = b2 ]; then
	# The check that matters: not "is it listed", but "is any version left".
	versions="$(list --b2-versions)" || die "FAILED: cannot list old versions after deleting; check by hand (console: Show versions)"
	n_versions=$(printf '%s' "$versions" | grep -c . || true)
	echo "Left including old and hidden versions: $n_versions"
fi
if [ "$n_left" != 0 ] || [ "${n_versions:-0}" != 0 ]; then
	echo "FAILED: $n_left current and ${n_versions:-0} total version(s) still in the bucket -- the secrets are still recoverable." >&2
	echo "Under Object Lock they cannot go until their retain-until date; otherwise delete them in the console with 'Show versions'." >&2
	exit 1
fi
echo "Done: no plaintext site_config_backup.json is left under $target, in any version."
