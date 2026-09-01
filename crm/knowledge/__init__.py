# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The sample knowledge pack the assistant answers product questions from.

Samples are markdown files in ``crm/knowledge/samples/`` with a small
frontmatter block, in the same shape as the help center's articles. They are
placeholder product knowledge — generic, accurate engineering reference for a
valve and instrumentation supplier — that a customer replaces with their own
catalogue. Every body opens with a line saying so, and the test suite checks
that the marker survives an edit.

This module deliberately imports no frappe: the assistant tier builds its
prompts from these files, and the agent package keeps its prompt-building
layers importable without a site. The samples directory is resolved relative
to this file, which works both from the working tree and from an installed app.

Unlike the help articles, samples are not cached: the pack is small, it is read
when a customer seeds their knowledge base rather than on every request, and a
freshly written file should show up without a restart.
"""

from __future__ import annotations

from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"

FRONTMATTER_DELIMITER = "---"
REQUIRED_KEYS = ("title", "category")
OPTIONAL_KEYS = ("tags", "product")


def load_samples() -> list[dict]:
	"""Every sample, parsed and sorted by filename.

	The filenames carry a numeric prefix, so filename order is the order the
	pack was written in -- the reading order a customer sees when they skim
	the samples before replacing them.
	"""
	return [
		parse_sample(path.stem, path.read_text(encoding="utf-8")) for path in sorted(SAMPLES_DIR.glob("*.md"))
	]


def parse_sample(name: str, text: str) -> dict:
	"""One markdown file into ``{name, title, category, tags, product, content}``.

	``tags`` and ``product`` are optional and default to an empty string, so a
	caller can pass them straight through to a knowledge record without a
	``None`` check. Raises ``ValueError`` on a malformed file rather than
	skipping it: these files ship with the code, so a bad one is a bug for the
	test suite to catch, not content to silently drop from the pack.
	"""
	lines = text.splitlines()
	if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
		raise ValueError(f"knowledge sample {name!r}: missing frontmatter opening '---'")

	meta: dict[str, str] = {}
	body_start = None
	for index, line in enumerate(lines[1:], start=1):
		if line.strip() == FRONTMATTER_DELIMITER:
			body_start = index + 1
			break
		if not line.strip():
			continue
		key, separator, value = line.partition(":")
		if not separator:
			raise ValueError(f"knowledge sample {name!r}: frontmatter line without ':': {line!r}")
		meta[key.strip()] = value.strip()

	if body_start is None:
		raise ValueError(f"knowledge sample {name!r}: frontmatter never closed with '---'")

	missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
	if missing:
		raise ValueError(f"knowledge sample {name!r}: frontmatter missing {missing}")

	content = "\n".join(lines[body_start:]).strip()
	if not content:
		raise ValueError(f"knowledge sample {name!r}: empty body")

	return {
		"name": name,
		"title": meta["title"],
		"category": meta["category"],
		**{key: meta.get(key, "") for key in OPTIONAL_KEYS},
		"content": content,
	}
