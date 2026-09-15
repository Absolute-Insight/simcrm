#!/usr/bin/env bash
# Checks for set-image-tags.sh.
#
# The rule that matters: only a TAG build writes `stable`. Every release
# produces both a main-push build and a tag build, from different commits, and
# when both wrote `stable` the last one to finish won -- which could leave
# `stable` on an image naming the previous version.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/set-image-tags.sh"
repo="absolute-insight/simcrm"
reg="ghcr.io/$repo"
failures=0

tags_for() { bash "$script" "$repo" "$1" "$2" "$3" 2>&1 | sed -n 's/^IMAGE_RELEASE_TAGS=//p'; }

expect() {
	local name="$1" got="$2" want="$3"
	if [ "$got" = "$want" ]; then
		echo "ok    $name"
	else
		echo "FAIL  $name"
		echo "        want: $want"
		echo "        got:  $got"
		failures=$((failures + 1))
	fi
}

expect "release tag gets its version and stable" \
	"$(tags_for refs/tags/v9.9.9 v9.9.9 abc1234)" \
	"$reg:v9.9.9,$reg:stable"

expect "main push gets main and NOT stable" \
	"$(tags_for refs/heads/main main abc1234)" \
	"$reg:main"

expect "rehearsal on develop gets develop only" \
	"$(tags_for refs/heads/develop develop abc1234)" \
	"$reg:develop"

expect "a non-version tag does not get stable" \
	"$(tags_for refs/tags/nightly-2026-09-14 nightly-2026-09-14 abc1234)" \
	"$reg:nightly-2026-09-14"

# The candidate is the same regardless of ref: the smoke test pulls it by name.
got=$(bash "$script" "$repo" refs/heads/main main abc1234 | sed -n 's/^IMAGE_BUILD_TAG=//p')
expect "candidate tag is sha-<short>" "$got" "$reg:sha-abc1234"

# Nothing but a tag build may ever name stable.
for ref in refs/heads/main refs/heads/develop refs/pull/1/merge; do
	if tags_for "$ref" "${ref##*/}" abc1234 | grep -q ":stable"; then
		echo "FAIL  $ref must never publish :stable"
		failures=$((failures + 1))
	fi
done

for n in 1 2 3 4; do
	args=(absolute-insight/simcrm refs/tags/v1.0.0 v1.0.0 abc1234)
	unset "args[$((n - 1))]"
	if bash "$script" "${args[@]}" >/dev/null 2>&1; then
		echo "FAIL  missing argument $n should be refused"
		failures=$((failures + 1))
	fi
done
echo "ok    missing arguments are refused"

echo
if [ "$failures" -ne 0 ]; then
	echo "$failures set-image-tags.sh check(s) failed"
	exit 1
fi
echo "all set-image-tags.sh checks passed"
