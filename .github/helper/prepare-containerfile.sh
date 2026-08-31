#!/bin/bash
#
# Rewrite frappe_docker's layered Containerfile for this project, in place.
#
#     bash .github/helper/prepare-containerfile.sh builds/images/layered/Containerfile
#
# Two rewrites, each asserted rather than trusted. This is checked-out
# third-party source; even pinned, it changes whenever the pin is bumped, and
# builds.yml runs only on a push to main or a tag -- so a rewrite that silently
# stopped applying would first be noticed during a release. Every failure below
# is therefore loud and specific about what to do.
#
# Kept out of builds.yml so image-build-inputs.yml can run exactly the same
# logic on every PR. Two copies of this sed would diverge, and the copy that
# diverged would be the one nobody runs until a release.
set -euo pipefail

file="${1:?usage: prepare-containerfile.sh <containerfile>}"
: "${FRAPPE_BUILD_IMAGE:?source .github/helper/image-pins.env first}"
: "${FRAPPE_BASE_IMAGE:?source .github/helper/image-pins.env first}"

# 1. Copy the pinned frappe into the builder stage.
#
# The Containerfile clones frappe from FRAPPE_PATH, and builds.yml sets that to
# a path inside the image rather than a URL, because `bench init
# --frappe-branch` becomes `git clone --branch` and that takes a branch or a tag
# and never a commit. So the source has to be on disk before `bench init` runs.
# The backend stage copies only the finished bench, so this adds nothing to the
# shipped image.
anchor='RUN --mount=type=secret,id=apps_json'
found=$(grep -c "^$anchor" "$file" || true)
if [[ "$found" != "1" ]]; then
    echo "::error::Expected exactly one '$anchor' line, found $found." >&2
    echo "::error::Upstream moved it; re-anchor this script against FRAPPE_DOCKER_REF." >&2
    grep -nE '^RUN|^COPY' "$file" >&2
    exit 1
fi

copy_line='COPY --chown=frappe:frappe frappe-src /home/frappe/frappe-src'
sed -i "s|^$anchor|$copy_line\n&|" "$file"

if [[ "$(grep -c "^$copy_line$" "$file")" != "1" ]]; then
    echo "::error::The frappe-src COPY was not inserted exactly once." >&2
    exit 1
fi

# 2. Point both base images at pinned digests instead of at the frappe branch.
#
# Missing one is not a build failure at this step -- it is a manifest-not-found
# error much later, far from its cause. That is what happened when a `base`
# stage was added upstream and only `builder` was being rewritten, so the check
# below catches any FROM still resolving through FRAPPE_BRANCH, including a
# stage added tomorrow.
sed -i "s|^FROM \${FRAPPE_IMAGE_PREFIX}/build:\${FRAPPE_BRANCH} AS builder|FROM ${FRAPPE_BUILD_IMAGE} AS builder|" "$file"
sed -i "s|^FROM \${FRAPPE_IMAGE_PREFIX}/base:\${FRAPPE_BRANCH} AS backend|FROM ${FRAPPE_BASE_IMAGE} AS backend|" "$file"

if grep -nE '^FROM .*\$\{FRAPPE_BRANCH\}' "$file" >&2; then
    echo "::error::A FROM line above still resolves through FRAPPE_BRANCH." >&2
    echo "::error::Upstream publishes those images only for its own branch names," >&2
    echo "::error::so this would look for a tag that does not exist." >&2
    echo "::error::Pin the new stage in .github/helper/image-pins.env." >&2
    exit 1
fi

echo "Containerfile prepared:"
grep -nE '^FROM |^COPY |^RUN ' "$file"
