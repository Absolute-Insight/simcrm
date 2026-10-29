# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Answers from reference sheets -- rows in, rows out. Pure, like ``knowledge``.

A reference sheet is a grid of figures (a flange drilling table, a bolt list):
a paraphrase that swaps one digit is a wrong flange. So the sheet's rows are
selected deterministically, the model only phrases the answer, and every
number the model writes is checked against the rows it cites. An answer that
fails the check is replaced by the rows themselves (:func:`fallback_answer`),
which is always what the sheet says.

Entries arrive as plain dicts (see ``crm.api.reference``)::

    {"name", "sheet", "sheet_title", "page", "label", "section", "search",
     "cells": [{"label", "value", "unit", "status", "note", "bbox"}], "bbox"}

A cell whose ``status`` is ``"questioned"`` has not been confirmed by the
company's engineers: its value never reaches the prompt, never counts as
support for a number, and is stripped before an entry leaves the server.
"""

from __future__ import annotations

import math
import re

QUESTIONED = "questioned"

# How many rows a question may pull into the prompt. A "6 inch SABS flange"
# with no class names seven classes; eight leaves room for them and nothing
# else, and each row is a few hundred characters.
DEFAULT_LIMIT = 8

# Rows scoring under this share of the best row are dropped: the right row
# outranks its neighbours by a whole token, and every neighbour handed to the
# model is a figure it might copy from the wrong line.
RELATIVE_FLOOR = 0.75

# A token found in more than this share of all rows ("flange", "mm") says
# little about which row is meant; two rarer ones together do.
SPECIFIC_SHARE = 0.2

STRONG_WEIGHT = 2.0

# How much a row's length discounts its score (0 = not at all).
LENGTH_WEIGHT = 0.3

# What each question word naming one of the row's columns adds.
COLUMN_WEIGHT = 2.5

# How many rows the deterministic answer prints. The chips carry the rest.
FALLBACK_ROWS = 3

INSTRUCTION = (
	"Below are rows from {company}'s reference sheets, quoted exactly. When they answer the "
	"question, answer from them alone: copy every figure exactly as the row gives it, with its "
	"unit, and name the rows you used in `cited_rows` by their id (R1, R2, ...). Say which row "
	"you are reading (size, standard, class) so the rep can check it. A value shown as "
	"'awaiting confirmation' has not been confirmed by engineering: say so, and never give or "
	"estimate a figure for it. If several rows could be meant and the question does not say "
	"which, give each briefly or ask which one. If the rows do not answer the question, say so. "
	"Never write the row ids in `answer`: the rep sees the rows themselves as links."
)

NO_ARTICLE_NOTE = (
	"No knowledge articles matched. Answer from the reference rows, or say they do not cover it."
)

AWAITING = "awaiting confirmation"

# --- normalisation -------------------------------------------------------------

_FRACTIONS = {
	"½": " 1/2",
	"¼": " 1/4",
	"¾": " 3/4",
	"⅛": " 1/8",
	"⅜": " 3/8",
	"⅝": " 5/8",
	"⅞": " 7/8",
}
_QUOTES = re.compile(r"[“”″ʺ]|''")
_THOUSANDS = re.compile(r"(\d),(\d{3})\b")

# An inch size in any of the ways a rep types one: 6", 6 inch, 1 1/2", 1-1/2in.
_INCH = re.compile(r"(?<![\w./])(\d+[ -]+\d+/\d+|\d+/\d+|\d+)\s*(?:\"|inches\b|inch\b|in\b)")
_MM = re.compile(r"(?<![\w.])(\d+)\s*mm\b")
_BORE = re.compile(r"\b(?:dn|nb)\s*(\d+)\b")
_KPA = re.compile(r"(?<![\w.])(\d+)\s*kpa\b")
_PN = re.compile(r"\bpn\s*(\d+)\b")
_CLASS = re.compile(r"\bclass\s*(\d+)\b|(?<![\w.])(\d+)\s*(?:lbs?\b|#)")
_TABLE = re.compile(r"\btable\s+([a-z]|\d+)\b")
_IP = re.compile(r"\bip\s*(\d\dk?)\b")

_SYNONYMS = {"ansi": "asme", "asa": "asme", "sans": "sabs", "inches": "inch"}

_TOKEN = re.compile(r"[a-z0-9]+(?:[./-][a-z0-9]+)*")
_SIZE_TOKEN = re.compile(r"^\d[\d/-]*(?:mm|in)$")
_STRONG_TOKEN = re.compile(r"^(?:\d[\d/-]*(?:mm|in|kpa|bar)|pn\d+|class\d+|table[a-z0-9]+|ip\d\dk?)$")

_STOPWORDS = frozenset(
	"the a an and or but of to in on at for with from as is are was be been it its "
	"this that these those there here how what where when why who which do does did "
	"i my me we our you your can could should would will need use used using size "
	"sizes please tell give show".split()
)


def normalise(text: str) -> str:
	"""Lower-case text with sizes, ratings and standards spelled one way.

	Questions and rows go through the same function, so "6 inch", '6"' and
	"6in" meet as ``6in``; "DN150" and "150 mm" as ``150mm``; "PN 16" as
	``pn16``; "class 150" and "150 lb" as ``class150``.
	"""
	text = (text or "").lower()
	for glyph, spelled in _FRACTIONS.items():
		text = text.replace(glyph, spelled)
	text = _QUOTES.sub('"', text)
	text = _THOUSANDS.sub(r"\1\2", text)
	text = _INCH.sub(lambda m: " " + re.sub(r"[ -]+", "-", m.group(1)) + "in ", text)
	# the tagged token and the bare number both: "SABS 1600" must still find
	# the row a sheet labels "1600 kPa"
	text = _MM.sub(r" \1mm \1 ", text)
	text = _BORE.sub(r" \1mm \1 ", text)
	text = _KPA.sub(r" \1kpa \1 ", text)
	text = _PN.sub(r" pn\1 \1 ", text)
	text = _CLASS.sub(lambda m: f" class{m.group(1) or m.group(2)} {m.group(1) or m.group(2)} ", text)
	text = _TABLE.sub(r" table\1 ", text)
	text = _IP.sub(r" ip\1 ", text)
	return text


def tokens(text: str) -> set[str]:
	"""The distinct search tokens of ``text``, compound tokens with their parts."""
	found: set[str] = set()
	for token in _TOKEN.findall(normalise(text)):
		token = _SYNONYMS.get(token, token)
		if token in _STOPWORDS:
			continue
		if len(token) > 1 or token.isdigit():
			found.add(token)
		if not _SIZE_TOKEN.match(token) and re.search(r"[./-]", token):
			for part in re.split(r"[./-]", token):
				if len(part) > 1 and part not in _STOPWORDS:
					found.add(_SYNONYMS.get(part, part))
	return found


def _size_tokens(found: set[str]) -> set[str]:
	return {token for token in found if _SIZE_TOKEN.match(token)}


def entry_text(entry: dict) -> str:
	"""Everything about a row a question may match: names, labels and values."""
	parts = [
		entry.get("sheet_title", ""),
		entry.get("section", ""),
		entry.get("label", ""),
		entry.get("search", ""),
	]
	for cell in entry.get("cells") or []:
		parts.append(cell.get("label", ""))
		if cell.get("status") != QUESTIONED:
			parts.append(f"{cell.get('value', '')} {cell.get('unit', '')}")
	return " ".join(str(part) for part in parts if part)


# --- selection -----------------------------------------------------------------


def build_index(entries: list[dict]) -> list[tuple[set[str], set[str], set[str]]]:
	"""Each row's search tokens, its own size tokens and its column-name tokens.

	The expensive half of :func:`select_entries` -- a few hundred rows of
	regex normalisation -- and it depends only on the rows, so a caller that
	keeps the rows between questions keeps this beside them.

	A row's own size is in its label and search words; a cell value such as a
	2" bolt is not the size of the flange it bolts.
	"""
	return [
		(
			tokens(entry_text(entry)),
			_size_tokens(tokens(f"{entry.get('label', '')} {entry.get('search', '')}")),
			tokens(" ".join(str(cell.get("label", "")) for cell in entry.get("cells") or [])),
		)
		for entry in entries
	]


def select_entries(
	question: str,
	entries: list[dict],
	limit: int = DEFAULT_LIMIT,
	index: list[tuple[set[str], set[str], set[str]]] | None = None,
) -> list[dict]:
	"""The rows that answer ``question``, best first; empty when none plausibly do.

	Scoring is inverse-frequency overlap, with sizes, ratings and classes
	counted double, discounted for long rows and raised for each word that
	names one of the row's columns. Two gates keep a near miss out of the
	prompt: a question that names a size never matches a row of another
	size, and a row needs either one strong token or two rare words in
	common -- "which valve for slurry?" shares "valve" with every material
	row and none of them.

	``index`` is :func:`build_index` of ``entries``, when the caller has it.
	"""
	asked = tokens(question)
	if not asked or not entries:
		return []
	if index is None:
		index = build_index(entries)
	asked_sizes = _size_tokens(asked)
	average = sum(len(found) for found, _sizes, _columns in index) / len(index) or 1.0

	frequency: dict[str, int] = {}
	for found, _sizes, _columns in index:
		for token in found & asked:
			frequency[token] = frequency.get(token, 0) + 1
	total = len(entries)

	scored = []
	for position, (entry, (found, sizes, columns)) in enumerate(zip(entries, index, strict=True)):
		if asked_sizes and sizes and not asked_sizes & sizes:
			continue
		common = found & asked
		if not common:
			continue
		strong = {token for token in common if _STRONG_TOKEN.match(token)}
		specific = {token for token in common if frequency[token] / total <= SPECIFIC_SHARE}
		if not strong and len(specific) < 2:
			continue
		score = sum(
			math.log(1 + total / frequency[token]) * (STRONG_WEIGHT if token in strong else 1.0)
			for token in common
		)
		# the same words matched in a short row say more than in a long one:
		# "2 1/2 inch in mm" is the line-size row, not a drilling row that
		# also mentions 2 1/2" among forty other words
		score /= 1 - LENGTH_WEIGHT + LENGTH_WEIGHT * len(found) / average
		# a word naming one of the row's columns ("OD", "PCD", "UNS") says the
		# question is about this kind of row, however common the column is
		score += COLUMN_WEIGHT * len(columns & asked)
		scored.append((score, position, entry))
	if not scored:
		return []
	scored.sort(key=lambda item: (-item[0], item[1]))
	floor = scored[0][0] * RELATIVE_FLOOR
	return [entry for score, _position, entry in scored if score >= floor][:limit]


# --- the prompt ----------------------------------------------------------------


def row_id(index: int) -> str:
	return f"R{index + 1}"


def _cell_line(cell: dict) -> str:
	if cell.get("status") == QUESTIONED:
		return f"- {cell.get('label', '')}: {AWAITING}"
	value = str(cell.get("value", "")).strip()
	unit = (cell.get("unit") or "").strip()
	return f"- {cell.get('label', '')}: {value}{' ' + unit if unit and value else ''}"


def describe(entry: dict) -> str:
	"""Where a row lives, in the words a rep would use to find it on paper."""
	place = f"{entry.get('sheet_title', '')}, page {entry.get('page', '')}"
	section = entry.get("section")
	return (
		f"{place} — {section}: {entry.get('label', '')}" if section else f"{place} — {entry.get('label', '')}"
	)


def reference_block(entries: list[dict], company: str = "the company") -> str:
	"""The rows as the model sees them: an id, where they are, and each cell."""
	sections = [f"# Reference sheets\n\n{INSTRUCTION.format(company=company)}"]
	for index, entry in enumerate(entries):
		lines = [f"[{row_id(index)}] {describe(entry)}"]
		lines.extend(_cell_line(cell) for cell in entry.get("cells") or [])
		sections.append("\n".join(lines))
	return "\n\n".join(sections)


def resolve_cited(cited_rows: list[str], entries: list[dict]) -> list[dict]:
	"""The prompt's rows the model named, in order, unknown ids dropped."""
	by_id = {row_id(index): entry for index, entry in enumerate(entries)}
	picked: list[dict] = []
	for raw in cited_rows or []:
		entry = by_id.get(str(raw).strip().strip("[]").upper())
		if entry is not None and entry not in picked:
			picked.append(entry)
	return picked


# --- the number check ----------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_UNITS = (
	"zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
	"sixteen seventeen eighteen nineteen twenty"
).split()
_TENS = {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
# A figure in words is still a figure: "thirty bolts" must meet the check like
# "30 bolts". "twenty four" becomes two numbers, which no row supports as a
# pair -- the safe direction: the rows are shown instead.
_NUMBER_WORDS = {
	**{word: str(value) for value, word in enumerate(_UNITS)},
	**{w: str(v) for w, v in _TENS.items()},
	"dozen": "12",
}
_WORD = re.compile(r"[a-z]+")


def _canonical(atom: str) -> str:
	if "." in atom:
		atom = atom.rstrip("0").rstrip(".")
	return atom.lstrip("0") or "0"


def _variants(atom: str) -> set[str]:
	"""Each way a written number may be meant: ``1,000`` is a thousand or one, ``51,33`` a decimal."""
	if "," not in atom:
		return {_canonical(atom)}
	return {_canonical(atom.replace(",", "")), _canonical(atom.replace(",", "."))}


def numbers(text: str) -> list[set[str]]:
	"""Every number in ``text``, each as the set of values it may stand for."""
	text = (text or "").lower()
	for glyph, spelled in _FRACTIONS.items():
		text = text.replace(glyph, spelled)
	text = _WORD.sub(
		lambda m: f" {_NUMBER_WORDS[m.group(0)]} " if m.group(0) in _NUMBER_WORDS else m.group(0), text
	)
	return [_variants(atom) for atom in _NUMBER.findall(text)]


def _supported_values(entries: list[dict], extra_texts: list[str]) -> set[str]:
	values: set[str] = set()
	texts = list(extra_texts)
	for entry in entries:
		texts.extend([entry.get("label", ""), entry.get("section", ""), str(entry.get("page", ""))])
		texts.append(entry.get("sheet_title", ""))
		for cell in entry.get("cells") or []:
			texts.append(cell.get("label", ""))
			if cell.get("status") != QUESTIONED:
				texts.append(str(cell.get("value", "")))
	for text in texts:
		for variants in numbers(text):
			values |= variants
	return values


def _withheld_values(rows: list[dict]) -> set[str]:
	return _values(
		[
			str(cell.get("value", ""))
			for row in rows
			for cell in row.get("cells") or []
			if cell.get("status") == QUESTIONED
		]
	)


def _values(texts: list[str]) -> set[str]:
	found: set[str] = set()
	for text in texts:
		for variants in numbers(text):
			found |= variants
	return found


# An answer splits into the claims it makes: lines, list items, sentences. A
# full stop splits only after a word or a bracket, never inside "285.0".
_CLAIM = re.compile(r"\n+|;\s+|(?<=[A-Za-z)\]])\.\s+")


def verify(
	answer: str, rows: list[dict], cited: list[dict] | None = None, extra_texts: list[str] | None = None
) -> tuple[list[dict] | None, list[str]]:
	"""Whether every figure in ``answer`` is on the sheet, and which rows it came from.

	Returns ``(rows_used, [])`` when it is, ``(None, unsupported)`` when not.

	Each claim (a line, a list item, a sentence) must take all of its figures
	from **one** row, or from ``extra_texts`` (the question, a cited article):
	"1600 kPa: 8 Off M20 x 75" read across two rows would pass a check of the
	whole answer against all of them, and is a bolt set that does not exist.
	The rows the model named in ``cited`` are tried first; any other prompt row
	that holds a claim's figures is the row that claim really came from, and
	is what the citation then shows. A questioned cell's value is never
	support: the model never saw it, so a model that wrote it guessed.
	"""
	extra = _values(extra_texts or [])
	order = list(cited or []) + [row for row in rows if row not in (cited or [])]
	supports = [_supported_values([row], []) for row in order]
	# The values withheld from the prompt. A model that writes one guessed it,
	# and the guess may well match the sheet's unconfirmed figure -- which is
	# then exactly the number the company has not stood behind. Refused even
	# when some other row happens to hold the same digits.
	withheld = _withheld_values(cited or rows) - extra
	used: list[dict] = []
	for claim in _CLAIM.split(answer or ""):
		missing = [variants for variants in numbers(claim) if not variants & extra]
		if not missing:
			continue
		guessed = [variants for variants in missing if variants & withheld]
		if guessed:
			return None, [min(variants) for variants in guessed]
		for row, allowed in zip(order, supports, strict=True):
			if all(variants & allowed for variants in missing):
				if row not in used:
					used.append(row)
				break
		else:
			return None, [min(variants) for variants in missing]
	return used or list(cited or []), []


def highlight(answer: str, entry: dict) -> list[int]:
	"""Which of a row's cells the answer quoted -- or all of them, when it quoted none."""
	given: set[str] = set()
	for variants in numbers(answer):
		given |= variants
	quoted = []
	for index, cell in enumerate(entry.get("cells") or []):
		if cell.get("status") == QUESTIONED:
			continue
		cell_numbers = numbers(str(cell.get("value", "")))
		if cell_numbers and all(variants & given for variants in cell_numbers):
			quoted.append(index)
	return quoted or list(range(len(entry.get("cells") or [])))


# The prompt's row ids, when a model writes them into the answer anyway:
# "(see R3)", "(Row R1: ...)", "per R2". Ids are one or two digits; a UNS
# number such as R30006 is not one.
_ROW_REF = re.compile(
	r"\s*\((?:see\s+)?(?:rows?\s+)?R\d{1,2}\b[^)]*\)|\b(?:see\s+|per\s+)?(?:rows?\s+)?R\d{1,2}\b(?!\w)", re.I
)


def strip_row_ids(answer: str) -> str:
	"""``answer`` without the prompt's row ids, which mean nothing to a rep."""
	text = _ROW_REF.sub("", answer or "")
	text = re.sub(r"[ \t]+([.,;:])", r"\1", text)
	return re.sub(r"[ \t]{2,}", " ", text).strip()


# --- the deterministic answer --------------------------------------------------


def fallback_answer(entries: list[dict]) -> str:
	"""The rows themselves, as plain text: always exactly what the sheet says."""
	blocks = []
	for entry in entries[:FALLBACK_ROWS]:
		lines = [f"{entry.get('label', '')} ({entry.get('sheet_title', '')}, page {entry.get('page', '')})"]
		lines.extend(_cell_line(cell) for cell in entry.get("cells") or [])
		blocks.append("\n".join(lines))
	heading = "Here is what the sheet says:" if len(blocks) == 1 else "These rows on the sheets match:"
	return heading + "\n\n" + "\n\n".join(blocks)


def public_cell(cell: dict) -> dict:
	"""A cell as it may leave the server: a questioned value is withheld."""
	shown = {key: cell.get(key) for key in ("label", "value", "unit", "status", "note", "bbox")}
	if cell.get("status") == QUESTIONED:
		shown["value"] = ""
	return shown
