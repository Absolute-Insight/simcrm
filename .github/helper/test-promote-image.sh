#!/usr/bin/env bash
# Exercise promote-image.sh without touching a registry.
#
# This exists because builds.yml runs only on main or a tag: before it, the
# promotion logic could not be executed anywhere except a live release, and a
# release is a bad place to find out that a shell loop mishandles its input.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
promote="$here/promote-image.sh"
repo="ghcr.io/absolute-insight/simcrm"
failures=0

check() {
	local name="$1" expected_rc="$2" expected_text="$3"
	shift 3
	local out rc
	# RELEASE_TAGS stands in for `git ls-remote`, so nothing here needs a remote.
	out=$(DRY_RUN=1 RELEASE_TAGS="${RELEASE_TAGS-v9.9.8 v9.9.9}" bash "$promote" "$@" 2>&1)
	rc=$?
	if [ "$rc" != "$expected_rc" ]; then
		echo "FAIL  $name: expected exit $expected_rc, got $rc"
		printf '%s\n' "$out" | sed 's/^/        /'
		failures=$((failures + 1))
		return
	fi
	if [ -n "$expected_text" ] && ! printf '%s' "$out" | grep -qF -- "$expected_text"; then
		echo "FAIL  $name: output did not contain: $expected_text"
		printf '%s\n' "$out" | sed 's/^/        /'
		failures=$((failures + 1))
		return
	fi
	echo "ok    $name"
}

# A release: version tag plus stable, both promoted from one candidate.
check "release tag promotes both tags" 0 \
	"imagetools create --tag $repo:v9.9.9 --tag $repo:stable $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"

# A rehearsal dispatch on a non-main ref: one tag, and crucially no stable.
check "non-main ref promotes one tag" 0 \
	"imagetools create --tag $repo:develop $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:develop"
check "non-main ref does not touch stable" 0 "" \
	"$repo:sha-abc1234" "$repo:develop"
if DRY_RUN=1 bash "$promote" "$repo:sha-abc1234" "$repo:develop" 2>&1 | grep -q ":stable"; then
	echo "FAIL  non-main ref must never promote :stable"
	failures=$((failures + 1))
fi

# Malformed input must fail loudly rather than becoming `--tag ""`.
check "trailing comma is ignored, not promoted as an empty tag" 0 \
	"imagetools create --tag $repo:v9.9.9 $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:v9.9.9,"
check "empty tag list is refused" 2 "no non-empty release tags" \
	"$repo:sha-abc1234" ",,"
check "missing candidate is refused" 2 "candidate image ref required" "" ""
check "missing tag argument is refused" 2 "release tags required" "$repo:sha-abc1234"

# --- `stable` only moves forward ---------------------------------------------
# Re-dispatching an old tag used to carry `stable` back to it.
RELEASE_TAGS="v9.9.9 v9.10.0 v10.0.0" check "an older release keeps its own tag" 0 \
	"imagetools create --tag $repo:v9.9.9 $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"
RELEASE_TAGS="v9.9.9 v9.10.0 v10.0.0" check "an older release says why stable stayed" 0 \
	"older than the newest release tag (v10.0.0)" \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"
# Ordered as versions, not as text: 9.10.0 is newer than 9.9.9.
RELEASE_TAGS="v9.9.9 v9.10.0" check "the newest release moves stable (9.10 > 9.9)" 0 \
	"imagetools create --tag $repo:v9.10.0 --tag $repo:stable $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:v9.10.0,$repo:stable"
# Tags that are not releases do not take part.
RELEASE_TAGS="v9.9.9 v99.0.0-rc.1 vectora nightly" check "non-release tags are ignored when ranking" 0 \
	"--tag $repo:stable" \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"
RELEASE_TAGS="" check "the first release ever moves stable" 0 \
	"--tag $repo:stable" \
	"$repo:sha-abc1234" "$repo:v0.1.0,$repo:stable"
ALLOW_STABLE_DOWNGRADE=1 RELEASE_TAGS="v9.9.9 v10.0.0" check "an explicit override moves stable back" 0 \
	"imagetools create --tag $repo:v9.9.9 --tag $repo:stable $repo:sha-abc1234" \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"
check "stable with no version beside it is refused" 2 "no vX.Y.Z tag beside it" \
	"$repo:sha-abc1234" "$repo:main,$repo:stable"

# --- a published version tag is never re-pointed -----------------------------
# These run for real against a fake `docker`: the refusal lives on the path
# DRY_RUN skips. The fake answers `imagetools inspect` from a file of
# "<ref> <digest>" lines and records every `imagetools create`.
shim="$(mktemp -d)"
trap 'rm -rf "$shim"' EXIT
cat >"$shim/docker" <<'SH'
#!/usr/bin/env bash
here="$(dirname "$0")"
case "$*" in
"buildx imagetools inspect"*)
	ref="${*: -1}"
	if [ -f "$here/registry-down" ]; then
		echo "ERROR: failed to do request: dial tcp: i/o timeout" >&2
		exit 1
	fi
	digest=$(awk -v r="$ref" '$1 == r { print $2 }' "$here/registry")
	if [ -z "$digest" ]; then
		# What ghcr answers for a tag that does not exist.
		echo "ERROR: $ref: not found" >&2
		exit 1
	fi
	printf '%s' "$digest"
	;;
"buildx imagetools create"*)
	echo "$*" >>"$here/created"
	# Point each --tag at the candidate, as the registry would, so the
	# digests promote-image.sh prints afterwards resolve.
	src="${*: -1}"
	digest=$(awk -v r="$src" '$1 == r { print $2 }' "$here/registry")
	prev=""
	for a in "$@"; do
		if [ "$prev" = "--tag" ]; then echo "$a $digest" >>"$here/registry.new"; fi
		prev="$a"
	done
	cat "$here/registry" >>"$here/registry.new"
	mv "$here/registry.new" "$here/registry"
	;;
esac
SH
chmod +x "$shim/docker"

# live <name> <expected-rc> <expected-text> <expect-create: yes|no> <args...>
live() {
	local name="$1" expected_rc="$2" expected_text="$3" expect_create="$4"
	shift 4
	local out rc created=no
	rm -f "$shim/created"
	out=$(PATH="$shim:$PATH" RELEASE_TAGS="${RELEASE_TAGS-v9.9.9}" bash "$promote" "$@" 2>&1)
	rc=$?
	[ -f "$shim/created" ] && created=yes
	if [ "$rc" != "$expected_rc" ] || [ "$created" != "$expect_create" ] ||
		{ [ -n "$expected_text" ] && ! printf '%s' "$out" | grep -qF -- "$expected_text"; }; then
		echo "FAIL  $name: want exit $expected_rc, create=$expect_create, text '$expected_text'; got exit $rc, create=$created"
		printf '%s\n' "$out" | sed 's/^/        /'
		failures=$((failures + 1))
		return
	fi
	echo "ok    $name"
}

old="sha256:1111111111111111111111111111111111111111111111111111111111111111"
new="sha256:2222222222222222222222222222222222222222222222222222222222222222"

printf '%s\n' "$repo:sha-abc1234 $new" >"$shim/registry"
live "a new version tag is promoted" 0 "$repo:v9.9.9" yes \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"

# The finding: the tag exists, and a rebuild of the same commit is other bytes.
printf '%s\n' "$repo:sha-abc1234 $new" "$repo:v9.9.9 $old" "$repo:stable $old" >"$shim/registry"
live "an existing version tag is not re-pointed" 1 "already published" no \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"
live "the precheck refuses it before the build" 1 "already published" no \
	--precheck "$repo:v9.9.9,$repo:stable"
ALLOW_TAG_OVERWRITE=1 live "an explicit override re-points it" 0 "" yes \
	"$repo:sha-abc1234" "$repo:v9.9.9,$repo:stable"

# Same bytes already there: nothing to refuse.
printf '%s\n' "$repo:sha-abc1234 $new" "$repo:v9.9.9 $new" >"$shim/registry"
live "promoting the digest that is already there is allowed" 0 "" yes \
	"$repo:sha-abc1234" "$repo:v9.9.9"

# Branch tags are meant to move.
printf '%s\n' "$repo:sha-abc1234 $new" "$repo:develop $old" >"$shim/registry"
live "a branch tag moves freely" 0 "" yes "$repo:sha-abc1234" "$repo:develop"
live "the precheck passes a branch build" 0 "precheck passed" no --precheck "$repo:develop"

printf '%s\n' "$repo:sha-abc1234 $new" >"$shim/registry"
live "the precheck passes an unpublished release" 0 "precheck passed" no \
	--precheck "$repo:v9.9.9,$repo:stable"

# A registry that cannot answer is not a registry that said "no such tag".
: >"$shim/registry-down"
live "an unreadable registry stops the promotion" 1 "could not tell whether" no \
	"$repo:sha-abc1234" "$repo:v9.9.9"
rm -f "$shim/registry-down"

echo
if [ "$failures" -ne 0 ]; then
	echo "$failures promote-image.sh check(s) failed"
	exit 1
fi
echo "all promote-image.sh checks passed"
