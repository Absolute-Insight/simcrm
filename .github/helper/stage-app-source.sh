#!/usr/bin/env bash
# Put THIS checkout's commit into the image build context, as a git repository
# bench can clone, parked on a branch bench can name.
#
#   stage-app-source.sh <dest> <branch> [<expected-sha>]
#   e.g. stage-app-source.sh builds/app-src/crm "$GITHUB_REF_NAME" "$GITHUB_SHA"
#
# <dest> must end in the app's name (crm): bench names an app after the
# directory it is handed.
#
# Why this exists. The image used to get the app with
#   {"url": "https://github.com/<repo>", "branch": "$GITHUB_REF_NAME"}
# so bench cloned whatever that branch pointed at WHEN THE CONTAINERFILE RAN.
# The guard in builds.yml verifies the checks of one commit, github.sha, and
# may wait up to forty minutes for them. A push landing on the branch during
# that wait was what got built: published as sha-<the verified commit>,
# smoke-tested and promoted, on the strength of checks that ran against a
# different commit. frappe and frappe_whatsapp were already pinned by commit
# (scripts/fetch-*.sh); the app this image exists to ship was not.
#
# The commit is taken from the checkout rather than fetched by SHA from
# GitHub: the checkout is already the commit the guard verified, and a second
# download is a second chance to get something else.
set -euo pipefail

dest="${1:?usage: stage-app-source.sh <dest> <branch> [<expected-sha>]}"
branch="${2:?usage: stage-app-source.sh <dest> <branch> [<expected-sha>]}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel)"

sha="$(git -C "$root" rev-parse HEAD)"
expected="${3:-$sha}"
if [ "$sha" != "$expected" ]; then
	echo "::error::The checkout is at $sha but the commit to build is $expected." >&2
	echo "::error::Refusing to build something the guard did not verify." >&2
	exit 1
fi

rm -rf "$dest"
mkdir -p "$(dirname "$dest")"
git init --quiet "$dest"
# file:// so --depth is honoured: a plain path makes git copy the whole object
# store, and <dest> is about to be COPY'd into a build layer.
git -C "$dest" fetch --quiet --depth 1 "file://$root" HEAD
git -C "$dest" checkout --quiet -B "$branch" FETCH_HEAD

staged="$(git -C "$dest" rev-parse HEAD)"
if [ "$staged" != "$expected" ]; then
	echo "::error::Staged $staged at $dest, expected $expected." >&2
	exit 1
fi
# Tracked files only, and none of them modified: the image must be the commit,
# not the commit plus whatever an earlier step left in the workspace.
if [ -n "$(git -C "$dest" status --porcelain)" ]; then
	echo "::error::$dest is not a clean checkout of $expected." >&2
	exit 1
fi

echo "app source: $expected on local branch '$branch' at $dest"
