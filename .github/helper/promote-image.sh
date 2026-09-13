#!/usr/bin/env bash
# Promote a verified candidate image to the tags people actually deploy.
#
# Split out of builds.yml so it can be exercised somewhere other than a
# release. builds.yml runs only on a push to main or a tag, so anything living
# inline there is first executed in production -- which is the whole reason the
# release tagging was wrong in the first place. image-build-inputs.yml runs
# this in DRY_RUN on every PR that touches it.
#
#   promote-image.sh <candidate-ref> <comma-separated-release-tags>
#   DRY_RUN=1 prints the command instead of touching the registry.
#
# `imagetools create` copies the manifest list rather than rebuilding, so the
# bytes behind the release tags are the bytes that were verified. Rebuilding
# would not be equivalent: building the same commit twice produces different
# digests, as the Set Image Tag comment in builds.yml records.
set -euo pipefail

src="${1:-}"
release_tags="${2:-}"

if [ -z "$src" ]; then
	echo "::error::promote-image.sh: candidate image ref required (argument 1)" >&2
	exit 2
fi
if [ -z "$release_tags" ]; then
	echo "::error::promote-image.sh: comma-separated release tags required (argument 2)" >&2
	exit 2
fi

# A trailing or doubled comma must not silently become a `--tag ""`, which
# buildx would reject with a far less obvious message.
# printf '%s\n', not '%s': without the trailing newline `read` discards the
# final field, so "v1.2.3,stable" promoted only v1.2.3 and a single tag with no
# comma in it promoted nothing at all. Caught by test-promote-image.sh.
tags=()
while IFS= read -r t; do
	[ -n "$t" ] || continue
	tags+=("$t")
done < <(printf '%s\n' "$release_tags" | tr ',' '\n')

if [ "${#tags[@]}" -eq 0 ]; then
	echo "::error::promote-image.sh: no non-empty release tags in '$release_tags'" >&2
	exit 2
fi

args=()
for t in "${tags[@]}"; do
	args+=(--tag "$t")
done

echo "verified candidate: $src"
for t in "${tags[@]}"; do
	echo "  -> $t"
done

if [ "${DRY_RUN:-0}" = "1" ]; then
	echo "DRY_RUN: docker buildx imagetools create ${args[*]} $src"
	exit 0
fi

docker buildx imagetools create "${args[@]}" "$src"

# Say what landed, by digest, so the log answers "which bytes" and not just
# "which tag". These must all equal the candidate's digest.
for t in "${tags[@]}"; do
	docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$t" | sed "s|^|  $t = |"
done
