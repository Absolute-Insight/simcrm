#!/bin/bash
#
# Clone frappe_whatsapp at the pinned commit into <dest>, parked on a local
# branch so bench has a name to ask for.
#
#     bash scripts/fetch-frappe-whatsapp.sh builds/app-src/frappe_whatsapp
#
# The same trick as fetch-frappe.sh, for the same reason: `git clone --branch`
# takes a branch or a tag, never a commit. <dest> must end in frappe_whatsapp,
# because bench names the app after the directory it is handed.
set -euo pipefail

dest="${1:?usage: fetch-frappe-whatsapp.sh <dest>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=./frappe-whatsapp-pin.env
source "$here/frappe-whatsapp-pin.env"

if [[ "$(git -C "$dest" rev-parse HEAD 2>/dev/null || true)" != "$FRAPPE_WHATSAPP_REF" ]]; then
    rm -rf "$dest"
    mkdir -p "$(dirname "$dest")"
    git init --quiet "$dest"
    git -C "$dest" remote add origin "$FRAPPE_WHATSAPP_REPO"
    git -C "$dest" fetch --quiet --depth 1 origin "$FRAPPE_WHATSAPP_REF" \
        || git -C "$dest" fetch --quiet origin
    git -C "$dest" checkout --quiet -B "$FRAPPE_WHATSAPP_PIN_BRANCH" "$FRAPPE_WHATSAPP_REF"
fi

echo "frappe_whatsapp: $FRAPPE_WHATSAPP_REF on local branch '$FRAPPE_WHATSAPP_PIN_BRANCH' at $dest"
