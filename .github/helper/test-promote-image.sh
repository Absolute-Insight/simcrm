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
	out=$(DRY_RUN=1 bash "$promote" "$@" 2>&1)
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

echo
if [ "$failures" -ne 0 ]; then
	echo "$failures promote-image.sh check(s) failed"
	exit 1
fi
echo "all promote-image.sh checks passed"
