#!/bin/bash
#
# Assert the pinned builder image can actually build the pinned frappe.
#
#     bash .github/helper/check-build-toolchain.sh <frappe-src-dir>
#
# frappe's source is pinned by commit (scripts/frappe-pin.env) and the builder
# image by digest (.github/helper/image-pins.env). Nothing tied the two
# together: they are bumped by different people for different reasons, and the
# pairing is only exercised by a release build.
#
# The failure this prevents is not hypothetical. Moving the devcontainer to a
# newer frappe put `engines: node >=24` against node 22, and `bench init` runs
# `yarn install --check-files`, which refused -- then offered a rollback prompt
# that nothing can answer in a non-interactive build. In the image build that is
# a failed release; here it is a red check on the PR that moves a pin.
set -euo pipefail

src="${1:?usage: check-build-toolchain.sh <frappe-src-dir>}"
: "${FRAPPE_BUILD_IMAGE:?source .github/helper/image-pins.env first}"

want_node=$(python3 -c '
import json, sys
print(json.load(open(sys.argv[1] + "/package.json")).get("engines", {}).get("node", ""))
' "$src")
# Anchored, not `.*=`: greedy matching ate the `>=` and left "3.14,<3.15", so
# the floor test below silently never fired.
want_python=$(grep -m1 '^requires-python' "$src/pyproject.toml" \
    | sed 's/^requires-python[[:space:]]*=[[:space:]]*//; s/"//g')

# The trailing newline matters: `read` returns non-zero at EOF without one, and
# under `set -e` that kills the script before it prints anything at all.
read -r got_node got_python < <(
    docker run --rm --entrypoint sh "$FRAPPE_BUILD_IMAGE" -c \
        'printf "%s %s\n" "$(node --version)" "$(python3 -c "import sys;print(\".\".join(map(str,sys.version_info[:3])))")"'
)

echo "pinned frappe wants   node ${want_node:-<unset>}, python ${want_python:-<unset>}"
echo "pinned builder image  node ${got_node}, python ${got_python}"

fail=0

# Only a ">=N" major floor is interpreted -- that is what frappe declares. Any
# other shape is reported rather than guessed at, because a check that silently
# passes on a spec it did not understand is worse than no check.
if [[ "$want_node" =~ ^\>=\ ?([0-9]+) ]]; then
    floor="${BASH_REMATCH[1]}"
    major="${got_node#v}"; major="${major%%.*}"
    if (( major < floor )); then
        echo "::error::Builder image ships node $major, pinned frappe needs >= $floor." >&2
        echo "::error::bench init runs 'yarn install --check-files', which refuses this" >&2
        echo "::error::and then hangs on a rollback prompt. Bump FRAPPE_BUILD_IMAGE." >&2
        fail=1
    fi
elif [[ -n "$want_node" ]]; then
    echo "::warning::Unhandled node engine spec '$want_node' -- not checked."
fi

if [[ "$want_python" =~ \>=\ ?([0-9]+)\.([0-9]+) ]]; then
    fmaj="${BASH_REMATCH[1]}"; fmin="${BASH_REMATCH[2]}"
    gmaj="${got_python%%.*}"; rest="${got_python#*.}"; gmin="${rest%%.*}"
    if (( gmaj < fmaj || (gmaj == fmaj && gmin < fmin) )); then
        echo "::error::Builder image ships python $got_python, pinned frappe needs >= $fmaj.$fmin." >&2
        fail=1
    fi
fi
if [[ "$want_python" =~ \<\ ?([0-9]+)\.([0-9]+) ]]; then
    cmaj="${BASH_REMATCH[1]}"; cmin="${BASH_REMATCH[2]}"
    gmaj="${got_python%%.*}"; rest="${got_python#*.}"; gmin="${rest%%.*}"
    if (( gmaj > cmaj || (gmaj == cmaj && gmin >= cmin) )); then
        echo "::error::Builder image ships python $got_python, pinned frappe requires < $cmaj.$cmin." >&2
        fail=1
    fi
fi

[[ $fail -eq 0 ]] || exit 1
echo "Builder image satisfies the pinned frappe."
