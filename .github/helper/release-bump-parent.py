#!/usr/bin/env python3
"""Decide whether a commit is a release version bump, from its DIFF.

    gh api repos/<owner>/<repo>/commits/<sha> | python3 release-bump-parent.py

Reads GitHub's "get a commit" JSON on stdin. If the commit is a pure version
bump it prints the parent's SHA and exits 0; the build guard in builds.yml then
reads the parent's checks in place of the bump's own, which can never exist --
semantic-release pushes the bump with a token that triggers no workflows.

Anything else exits 1 with the reason on stderr, and the guard waits for the
commit's own checks like any other commit. Exit 2 means the input could not be
read at all, and the guard stops.

Inheriting checks is a trust decision, so it is made on content. The guard used
to look at the subject and the list of files touched and nothing else, while
its comment said "one sed of the version string": any Python added to
crm/__init__.py -- which frappe imports at every start -- under a
`chore(release):` subject would have been published on the strength of tests
that never ran against it. A bump is exactly this, and nothing wider:

    -__version__ = "X.Y.Z"
    +__version__ = "A.B.C"

Stdlib only, so it needs nothing installed on the runner. Exercised at PR time
by test-release-bump-parent.sh, because builds.yml itself runs only on a push
to main or a tag.
"""

import json
import re
import sys

BUMP_FILE = "crm/__init__.py"
SUBJECT_PREFIX = "chore(release):"
VERSION_LINE = re.compile(r'__version__ = "\d+\.\d+\.\d+"')


def not_a_bump(reason):
	print(f"not a release bump: {reason}", file=sys.stderr)
	sys.exit(1)


def main():
	try:
		commit = json.load(sys.stdin)
		subject = commit["commit"]["message"].split("\n", 1)[0]
		parents = [p["sha"] for p in commit["parents"]]
		files = commit.get("files") or []
	except (ValueError, KeyError, TypeError, AttributeError) as e:
		print(f"release-bump-parent.py: cannot read the commit JSON: {e!r}", file=sys.stderr)
		sys.exit(2)

	if not subject.startswith(SUBJECT_PREFIX):
		not_a_bump(f"subject does not start with {SUBJECT_PREFIX!r}")
	if len(parents) != 1:
		not_a_bump(f"{len(parents)} parents; a bump has exactly one")
	if [f.get("filename") for f in files] != [BUMP_FILE]:
		not_a_bump(f"touches {[f.get('filename') for f in files]}, not only {BUMP_FILE}")

	changed = files[0]
	if changed.get("status") != "modified":
		not_a_bump(f"{BUMP_FILE} is {changed.get('status')!r}, not modified")
	if (changed.get("additions"), changed.get("deletions")) != (1, 1):
		not_a_bump(
			f"{BUMP_FILE} has +{changed.get('additions')} -{changed.get('deletions')} lines, not +1 -1"
		)

	# GitHub leaves `patch` out for a binary or oversized diff. No patch, no
	# evidence -- and no evidence is not a bump.
	patch = changed.get("patch")
	if not isinstance(patch, str) or not patch:
		not_a_bump(f"GitHub returned no patch for {BUMP_FILE}")

	removed, added = [], []
	for line in patch.split("\n"):
		if line.startswith("@@") or line.startswith(" "):
			continue
		if line.startswith("-"):
			removed.append(line[1:])
		elif line.startswith("+"):
			added.append(line[1:])
		else:
			# "\ No newline at end of file", or anything else this does not
			# recognise: a version bump produces neither.
			not_a_bump(f"unexpected line in the patch: {line!r}")

	if len(removed) != 1 or len(added) != 1:
		not_a_bump(f"patch removes {len(removed)} and adds {len(added)} lines, not one of each")
	for line in removed + added:
		if not VERSION_LINE.fullmatch(line):
			not_a_bump(f"changed line is not a version string: {line!r}")
	if removed == added:
		not_a_bump("the version did not change")

	print(parents[0])


if __name__ == "__main__":
	main()
