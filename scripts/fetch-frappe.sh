#!/bin/bash
#
# Clone frappe at the pinned commit into <dest>, parked on a local branch.
#
#     bash scripts/fetch-frappe.sh ~/frappe
#
# Then hand that directory to bench:
#
#     bench init --frappe-path ~/frappe --frappe-branch "$FRAPPE_PIN_BRANCH" ...
#
# Why a local clone rather than `bench init --frappe-path <url> --frappe-branch
# <ref>`: bench builds the clone as `git clone <url> --branch <tag> --depth 1`
# (bench/app.py), and `git clone --branch` takes a branch or a tag, never a
# commit. Pinning by commit therefore has to happen here, before bench sees it,
# and bench gets a branch name that exists because this script just made it.
#
# Sourcing this file's pin from one place is the point: the devcontainer, the
# server/migration/e2e lanes and the published image all resolve frappe through
# scripts/frappe-pin.env, so they cannot drift apart the way they did when four
# workflows each carried their own copy of a repo URL that turned out not to
# exist.
set -euo pipefail

dest="${1:?usage: fetch-frappe.sh <dest>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=./frappe-pin.env
source "$here/frappe-pin.env"

if [[ "$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)" != "$FRAPPE_REF" ]]; then
    rm -rf "$dest"
    git init --quiet "$dest"
    git -C "$dest" remote add origin "$FRAPPE_REPO"
    # github.com serves an arbitrary commit to `fetch --depth 1`
    # (allowAnySHA1InWant), so a pinned checkout stays a one-commit download.
    # The fallback covers a mirror that does not allow it.
    git -C "$dest" fetch --quiet --depth 1 origin "$FRAPPE_REF" \
        || git -C "$dest" fetch --quiet origin
    git -C "$dest" checkout --quiet -B "$FRAPPE_PIN_BRANCH" "$FRAPPE_REF"
fi

echo "frappe: $FRAPPE_REF on local branch '$FRAPPE_PIN_BRANCH' at $dest"
