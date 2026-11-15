#!/usr/bin/env bash
# Promote a verified candidate image to the tags people actually deploy.
#
# Split out of builds.yml so it can be exercised somewhere other than a
# release. builds.yml runs only on a push to main or a tag, so anything living
# inline there is first executed in production -- which is the whole reason the
# release tagging was wrong in the first place. image-build-inputs.yml runs
# test-promote-image.sh on every PR that touches it.
#
#   promote-image.sh <candidate-ref> <comma-separated-release-tags>
#   promote-image.sh --precheck <comma-separated-release-tags>
#
#   DRY_RUN=1                 print the command instead of touching the registry
#   ALLOW_TAG_OVERWRITE=1     let an existing vX.Y.Z tag be re-pointed
#   ALLOW_STABLE_DOWNGRADE=1  let `stable` move to a version below the newest
#   RELEASE_TAGS="v1.0.0 ..." the repository's release tags, for tests; unset,
#                             they are read with `git ls-remote`
#
# `imagetools create` copies the manifest list rather than rebuilding, so the
# bytes behind the release tags are the bytes that were verified. Rebuilding
# would not be equivalent: building the same commit twice produces different
# digests, as the Set Image Tag comment in builds.yml records.
#
# Which is exactly why two things are refused here.
#
# A version tag that already exists is never re-pointed. deploy/.env.example
# tells operators a release tag is immutable "because the git tag is", and
# nothing enforced it: dispatching builds.yml on an old tag a second time --
# or a release whose tag push and whose dispatch both fired -- rebuilt the
# commit, got different bytes, and moved vX.Y.Z onto them. Every host pinned
# to that tag would then receive a different image on its next `pull`, under
# a name that had not changed.
#
# And `stable` only moves forward. The same re-dispatch of an old tag also
# carried `stable` back to it, so the "newest release" pointer named an older
# one until the next release happened to correct it.
#
# --precheck asks the first question before the build instead of after it: a
# version tag that is already published fails in seconds, not after an hour
# of multi-arch build.
set -euo pipefail

precheck=0
if [ "${1:-}" = "--precheck" ]; then
	precheck=1
	src=""
	release_tags="${2:-}"
else
	src="${1:-}"
	release_tags="${2:-}"
	if [ -z "$src" ]; then
		echo "::error::promote-image.sh: candidate image ref required (argument 1)" >&2
		exit 2
	fi
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

version_re='^v[0-9]+\.[0-9]+\.[0-9]+$'

# The release this build is for, if it is one: the vX.Y.Z among the tags.
version=""
for t in "${tags[@]}"; do
	if [[ "${t##*:}" =~ $version_re ]]; then
		version="${t##*:}"
	fi
done

# --- `stable` only moves forward --------------------------------------------
wants_stable=0
for t in "${tags[@]}"; do
	if [ "${t##*:}" = "stable" ]; then wants_stable=1; fi
done

# Not in --precheck: that only answers the version-tag question, and the
# warning below belongs in the log once, beside the promotion it explains.
if [ "$precheck" = "0" ] && [ "$wants_stable" = "1" ] && [ "${ALLOW_STABLE_DOWNGRADE:-0}" != "1" ]; then
	if [ -z "$version" ]; then
		# set-image-tags.sh only ever pairs `stable` with a version tag. Without
		# one there is nothing to compare, so there is nothing to justify it.
		echo "::error::promote-image.sh: \`stable\` requested with no vX.Y.Z tag beside it; refusing to move it" >&2
		exit 2
	fi
	if [ -n "${RELEASE_TAGS+set}" ]; then
		known="$RELEASE_TAGS"
	elif ! known=$(git ls-remote --tags --refs "${RELEASE_TAGS_REMOTE:-origin}" 'v*' | sed 's|.*refs/tags/||'); then
		echo "::error::promote-image.sh: could not list the repository's release tags, so cannot tell whether $version is the newest. Nothing promoted." >&2
		exit 1
	fi
	newest=$(printf '%s\n' $known "$version" | grep -E "$version_re" | sort -V | tail -n 1)
	if [ "$newest" != "$version" ]; then
		echo "::warning::promote-image.sh: $version is older than the newest release tag ($newest); \`stable\` stays where it is. Set ALLOW_STABLE_DOWNGRADE=1 (allow_stable_downgrade on a dispatch) to move it anyway."
		kept=()
		for t in "${tags[@]}"; do
			if [ "${t##*:}" != "stable" ]; then kept+=("$t"); fi
		done
		tags=("${kept[@]}")
	fi
fi

# --- a published version tag is never re-pointed -----------------------------
# Prints the tag's digest, or nothing if the tag does not exist. Any failure
# that is not plainly "no such tag" stops the run: guessing "absent" on a
# registry error is how a tag gets overwritten after all.
existing_digest() {
	local ref="$1" out
	if out=$(docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$ref" 2>&1); then
		printf '%s' "$out" | tr -d '[:space:]'
		return 0
	fi
	if printf '%s' "$out" | grep -qiE 'not found|manifest unknown'; then
		return 0
	fi
	echo "::error::promote-image.sh: could not tell whether $ref already exists:" >&2
	printf '%s\n' "$out" | sed 's/^/    /' >&2
	return 1
}

if [ "${DRY_RUN:-0}" != "1" ] && [ "${ALLOW_TAG_OVERWRITE:-0}" != "1" ]; then
	src_digest=""
	for t in "${tags[@]}"; do
		[[ "${t##*:}" =~ $version_re ]] || continue
		have=$(existing_digest "$t") || exit 1
		[ -n "$have" ] || continue
		if [ "$precheck" = "0" ]; then
			if [ -z "$src_digest" ]; then
				src_digest=$(docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$src" | tr -d '[:space:]')
			fi
			# Promoting the bytes that are already there changes nothing.
			if [ "$have" = "$src_digest" ]; then continue; fi
		fi
		echo "::error::promote-image.sh: $t is already published ($have) and a release tag is immutable. Nothing promoted." >&2
		echo "::error::A rebuild of the same commit is a different image; hosts pinned to this tag would silently change on their next pull." >&2
		echo "::error::To replace it deliberately: gh workflow run builds.yml --ref ${t##*:} -f overwrite_release_tag=true" >&2
		exit 1
	done
fi

if [ "$precheck" = "1" ]; then
	echo "precheck passed: no published version tag would be re-pointed"
	exit 0
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
