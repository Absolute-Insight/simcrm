#!/usr/bin/env bash
# Work out which tags a build publishes.
#
#   set-image-tags.sh <repo-lowercase> <github-ref> <ref-name> <short-sha>
#
# Prints KEY=VALUE lines for $GITHUB_ENV. Split out of builds.yml so the rules
# can be tested at PR time -- builds.yml itself runs only on a push to main or
# a tag, so anything inline there is first executed during a release.
#
# Three tags, none content-addressed:
#   sha-<short>  the build candidate; always exactly this COMMIT, but NOT these
#                bytes -- building one commit twice gives two digests, because
#                transitive python and node dependencies resolve at build time
#   <ref_name>   `main`, or the release tag (immutable in practice, as the git
#                tag is)
#   stable       the newest RELEASE
#
# `stable` is written by a tag build only. It used to be written by a main
# build as well, and every release produces both: semantic-release pushes the
# bump to main (one build) and then the tag (another). Those are DIFFERENT
# commits -- the main build predates the version bump -- and both raced to
# write `stable`, so whichever finished last won. A main build landing last
# left `stable` on an image whose crm/__init__.py still named the PREVIOUS
# version. Restricting it to tags also makes the name honest: `stable` is the
# newest release, not the newest push to a branch.
#
# A build of any other ref -- `gh workflow run builds.yml --ref develop`, the
# documented rehearsal -- gets its own ref name and the candidate, never
# `stable`.
set -euo pipefail

repo="${1:-}"
github_ref="${2:-}"
ref_name="${3:-}"
short_sha="${4:-}"

for v in repo github_ref ref_name short_sha; do
	if [ -z "${!v}" ]; then
		echo "::error::set-image-tags.sh: $v is required" >&2
		exit 2
	fi
done

registry="ghcr.io/${repo}"
sha_tag="sha-${short_sha}"
release_tags="${registry}:${ref_name}"

case "$github_ref" in
	refs/tags/v*) release_tags="${release_tags},${registry}:stable" ;;
esac

echo "IMAGE_BUILD_TAG=${registry}:${sha_tag}"
echo "IMAGE_RELEASE_TAGS=${release_tags}"
echo "IMAGE_SHA_TAG=${sha_tag}"
echo "IMAGE_REPO=${repo}"
