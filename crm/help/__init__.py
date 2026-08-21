# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The in-app help center's content, and its only loader.

Articles are markdown files in ``crm/help/articles/`` with a small frontmatter
block. They ship with the app so the help center works offline and is versioned
with the code it documents — a screen and its article change in the same commit,
never on a separately hosted docs site that drifts.

This module deliberately imports no frappe: the assistant tier
(``crm.agent.knowledge``) grounds its answers on the same articles, and the
agent package keeps its prompt-building layers importable without a site. The
articles directory is resolved relative to this file, which works both from the
working tree and from an installed app.

One source of help: the help center renders these files, the assistant quotes
them. Editing an article updates both surfaces.
"""

from __future__ import annotations

import copy
import functools
from pathlib import Path

ARTICLES_DIR = Path(__file__).parent / "articles"

# Display order of categories in the help center. An article naming a category
# absent from this list is a bug the loader refuses, not a sorting surprise.
CATEGORY_ORDER = [
	"Getting started",
	"Working with records",
	"Proactive selling",
	"Analytics & reporting",
	"Assistant & customisation",
]

FRONTMATTER_DELIMITER = "---"
REQUIRED_KEYS = ("title", "category", "order")


def load_articles() -> list[dict]:
	"""Every article, parsed and sorted by (category order, article order).

	Parsed once per process -- the files ship with the code, so they change
	when the code does and a restart is the invalidation. Returns a deep copy
	on every call so a caller mutating its copy cannot poison another surface:
	the help center and the assistant both read this, on every request.
	"""
	return copy.deepcopy(_load_articles_once())


@functools.lru_cache(maxsize=1)
def _load_articles_once() -> list[dict]:
	articles = [
		parse_article(path.stem, path.read_text(encoding="utf-8"))
		for path in sorted(ARTICLES_DIR.glob("*.md"))
	]
	articles.sort(key=lambda a: (CATEGORY_ORDER.index(a["category"]), a["order"], a["name"]))
	return articles


def parse_article(name: str, text: str) -> dict:
	"""One markdown file into ``{name, title, category, order, content}``.

	Raises ``ValueError`` on a malformed file rather than skipping it: these
	files ship with the code, so a bad one is a bug for the test suite to catch,
	not content to silently drop from the help center.
	"""
	lines = text.splitlines()
	if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
		raise ValueError(f"help article {name!r}: missing frontmatter opening '---'")

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
			raise ValueError(f"help article {name!r}: frontmatter line without ':': {line!r}")
		meta[key.strip()] = value.strip()

	if body_start is None:
		raise ValueError(f"help article {name!r}: frontmatter never closed with '---'")

	missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
	if missing:
		raise ValueError(f"help article {name!r}: frontmatter missing {missing}")
	if meta["category"] not in CATEGORY_ORDER:
		raise ValueError(
			f"help article {name!r}: unknown category {meta['category']!r}. "
			f"Add it to CATEGORY_ORDER or use one of {CATEGORY_ORDER}."
		)
	try:
		order = int(meta["order"])
	except ValueError as exc:
		raise ValueError(f"help article {name!r}: order must be an integer") from exc

	content = "\n".join(lines[body_start:]).strip()
	if not content:
		raise ValueError(f"help article {name!r}: empty body")

	return {
		"name": name,
		"title": meta["title"],
		"category": meta["category"],
		"order": order,
		"content": content,
	}
