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

# A word in at most this many rows is enough on its own to select them.
RARE_COUNT = 3

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
# A bare "in" is the word, not the mark, before a unit no inch converts to
# ("600 in bar", "150 in inches") and after a rating or bore keyword ("PN 16
# in mm"): that number is the rating or the bore, never a 16" flange. Before
# a length it stays the mark: "1/2 in mm" asks for 1/2" in millimetres.
_INCH = re.compile(
	r"(?<![\w./])(\d+[ -]+\d+/\d+|\d+/\d+|\d+)\s*-?\s*"
	r"(?:\"|inches\b|inch\b|in\b(?!\s*(?:bar\b|kpa\b|mpa\b|psi\b|inch)))"
)
_RATED = re.compile(r"\b(?:class|pn|dn|nb)\s*$")
_MM = re.compile(r"(?<![\w.])(\d+)\s*mm\b")
_BORE = re.compile(r"\b(?:dn|nb)\s*(\d+)\b|(?<![\w.])(\d+)\s*(?:nb|dn)\b")
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


def _inch(match: re.Match) -> str:
	# a rating's number is never a size, however it is followed
	if _RATED.search(match.string, max(0, match.start() - 12), match.start()):
		return match.group(0)
	return " " + re.sub(r"[ -]+", "-", match.group(1)) + "in "


def normalise(text: str) -> str:
	"""Lower-case text with sizes, ratings and standards spelled one way.

	Questions and rows go through the same function, so "6 inch", '6"' and
	"6in" meet as ``6in``; "DN150" and "150 mm" as ``150mm``; "PN 16" as
	``pn16``; "class 150" and "150 lb" as ``class150`` -- also when "in" and a
	unit follow ("PN 16 in mm" asks for PN16 in millimetres, not a 16" size).
	"""
	text = (text or "").lower()
	for glyph, spelled in _FRACTIONS.items():
		text = text.replace(glyph, spelled)
	text = _QUOTES.sub('"', text)
	text = _THOUSANDS.sub(r"\1\2", text)
	text = _INCH.sub(_inch, text)
	# the tagged token and the bare number both: "SABS 1600" must still find
	# the row a sheet labels "1600 kPa"
	text = _MM.sub(r" \1mm \1 ", text)
	text = _BORE.sub(lambda m: f" {m.group(1) or m.group(2)}mm {m.group(1) or m.group(2)} ", text)
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
	size, and a row needs one strong token, two uncommon words, or one word
	almost no row has -- "which valve for slurry?" shares "valve" with every
	material row and nothing else with any of them.

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
		# a word only a handful of rows contain ("LTCS", "Hastelloy") names its row
		rare = {token for token in common if frequency[token] <= RARE_COUNT and len(token) >= 4}
		if not strong and len(specific) < 2 and not rare:
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


def withhold(text: str, entry: dict) -> str:
	"""``text`` -- a row's label or section -- without the row's questioned values.

	A pack may spell a cell's figure into the label ('1/4" = 6 mm') or name a
	questioned standard there ("ASME B16.5"): withholding the cell alone
	still printed it. A value is cut where the text spells it with its unit,
	or where it is more than a bare number. A bare number is left -- the 12
	of a 12" flange's label is its size, not its questioned bolt count -- and
	:func:`_supported_values` keeps it from vouching for the questioned one.
	"""
	text = text or ""
	for cell in entry.get("cells") or []:
		value = str(cell.get("value", "")).strip()
		if cell.get("status") != QUESTIONED or not re.search(r"\d", value):
			continue
		unit = (cell.get("unit") or "").strip()
		spelled = [re.escape(value) + r"\s*" + re.escape(unit)] if unit else []
		if not re.fullmatch(r"[\d.,]+", value):
			spelled.append(re.escape(value))
		for pattern in spelled:
			text = re.sub(rf"(?<![\w./]){pattern}(?!\w)", f"({AWAITING})", text, flags=re.I)
	return text


def public_label(entry: dict) -> str:
	"""The row's label as a rep or the model may read it."""
	return withhold(entry.get("label", ""), entry)


def describe(entry: dict) -> str:
	"""Where a row lives, in the words a rep would use to find it on paper."""
	place = f"{entry.get('sheet_title', '')}, page {entry.get('page', '')}"
	section = withhold(entry.get("section", ""), entry)
	label = public_label(entry)
	return f"{place} — {section}: {label}" if section else f"{place} — {label}"


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

# A figure as one token: a sign only where it cannot be a hyphen ("-20ºF",
# not the "15-20" of a range), a mixed or simple fraction whole ("1 3/8" is
# not "3/8"), a decimal or thousands comma kept with its digits.
_NUMBER = re.compile(r"(?:(?<![\w)])(-))?(?<![\d.])(\d+[ -]+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)*)")
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
	if "/" in atom:
		whole, _, fraction = re.sub(r"[ -]+", " ", atom).rpartition(" ")
		top, bottom = fraction.split("/")
		fraction = f"{top.lstrip('0') or '0'}/{bottom.lstrip('0') or '0'}"
		return f"{whole.lstrip('0') or '0'} {fraction}" if whole else fraction
	if "," in atom:
		# "1,000" and "12,500.5" are thousands; "51,33" is a decimal comma. The
		# last group is three digits before any decimal point of its own.
		groups = atom.split(",")
		if all(len(group) == 3 for group in [*groups[1:-1], groups[-1].split(".")[0]]):
			atom = "".join(groups)
		elif len(groups) == 2:
			atom = ".".join(groups)
		else:
			atom = "".join(groups)
	if "." in atom:
		atom = atom.rstrip("0").rstrip(".")
	return atom.lstrip("0") or "0"


def numbers(text: str) -> list[set[str]]:
	"""Every number in ``text``, each as the set of values it stands for."""
	# a PDF's minus is often U+2212 or an en dash
	text = (text or "").lower().replace("\u2212", "-").replace("\u2013", "-")
	for glyph, spelled in _FRACTIONS.items():
		text = text.replace(glyph, spelled)
	text = _WORD.sub(
		lambda m: f" {_NUMBER_WORDS[m.group(0)]} " if m.group(0) in _NUMBER_WORDS else m.group(0), text
	)
	found = []
	for sign, atom in _NUMBER.findall(text):
		parts = [atom]
		mixed = re.fullmatch(r"(\d+)[ -]+(\d+)/(\d+)", atom)
		if mixed and int(mixed.group(2)) >= int(mixed.group(3) or 0):
			# not a mixed fraction: "SABS 1123 1600/3" is a standard and a class
			parts = [mixed.group(1), f"{mixed.group(2)}/{mixed.group(3)}"]
		for index, part in enumerate(parts):
			value = _canonical(part)
			found.append({f"-{value}" if sign and index == 0 and value != "0" else value})
	return found


def _supported_values(entries: list[dict], extra_texts: list[str]) -> set[str]:
	texts = list(extra_texts)
	confirmed = []
	for entry in entries:
		texts.extend(
			[public_label(entry), withhold(entry.get("section", ""), entry), str(entry.get("page", ""))]
		)
		texts.append(entry.get("sheet_title", ""))
		for cell in entry.get("cells") or []:
			texts.append(cell.get("label", ""))
			if cell.get("status") != QUESTIONED:
				confirmed.append(str(cell.get("value", "")))
	confirmed_values = _values(confirmed)
	# a figure the row questions is support only where a confirmed cell holds
	# it: the label's own 12" does not vouch for a questioned count of 12
	return (_values(texts) | confirmed_values) - (_withheld_values(entries) - confirmed_values)


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
	"""Every figure ``texts`` can vouch for.

	An improper fraction also vouches for its parts: on these sheets "1600/3"
	is SABS class 1600 and "16/3" is PN16, so an answer saying "1600 kPa" is
	reading that row. A proper one does not -- "5/8" is a bolt size, and its 5
	and 8 are no bolt count -- and neither does a mixed one: "1 3/8" never
	vouches for "3/8".
	"""
	found: set[str] = set()
	for text in texts:
		for variants in numbers(text):
			found |= variants
			for value in variants:
				if "/" in value and " " not in value:
					top, bottom = (part.lstrip("-") for part in value.split("/"))
					# 1600/3 is a class; 5/8 is an inch size whose digits are not figures
					if int(top or 0) >= int(bottom or 0):
						found.update((top, bottom))
	return found


# An answer splits into the claims it makes: lines, list items, sentences. A
# full stop splits only after a word or a bracket, never inside "285.0".
_CLAIM = re.compile(r"\n+|;\s+|(?<=[A-Za-z)\]])\.\s+")


def trim_comparisons(answer: str, rows: list[dict]) -> str:
	"""``answer`` without claims that only compare rows by name.

	"The Class 300 flange has a larger PCD than the Class 150 flange" holds no
	figure of its own -- only the labels of two rows -- so no single row
	supports it and :func:`verify` would throw the whole answer away. Such a
	claim is dropped instead: removing a sentence can only take a figure out
	of an answer, never put one in. A claim with any figure that is not a row
	label (a value, or a label number no prompt row has) stays, and is checked.
	"""
	labels = [_values([public_label(row)]) for row in rows]
	every_label = set().union(*labels) if labels else set()
	supports = [_supported_values([row], []) for row in rows]
	pieces = re.split(f"({_CLAIM.pattern})", answer or "")
	kept: list[str] = []
	for index in range(0, len(pieces), 2):
		claim = pieces[index]
		separator = pieces[index + 1] if index + 1 < len(pieces) else ""
		figures = numbers(claim)
		one_row = any(all(v & allowed for v in figures) for allowed in supports)
		if figures and not one_row and all(v & every_label for v in figures):
			continue
		kept.append(claim + separator)
	return "".join(kept).strip()


def verify(
	answer: str, rows: list[dict], cited: list[dict] | None = None, extra_texts: list[str] | None = None
) -> tuple[list[dict] | None, list[str]]:
	"""Whether every figure in ``answer`` is on the sheet, and which rows it came from.

	Returns ``(rows_used, [])`` when it is, ``(None, unsupported)`` when not.

	Each claim (a line, a list item, a sentence) must take all of its figures
	from **one** row: "1600 kPa: 8 Off M20 x 75" read across two rows would
	pass a check of the whole answer against all of them, and is a bolt set
	that does not exist. The rows the model named in ``cited`` are tried
	first; any other prompt row that holds a claim's figures is the row that
	claim really came from, and is what the citation then shows.

	The question is **not** support: "is the PCD 241 mm?" answered "yes, 241 mm"
	must fail when the row says 240.0. ``extra_texts`` (the knowledge articles
	in the prompt, administrator-written) may supply a figure no row holds --
	but never one that is a withheld value of a prompt row. A questioned
	cell's value is never support: the model never saw it, so a model that
	wrote it guessed.
	"""
	extra = _values(extra_texts or [])
	# Values withheld from the prompt. A model that writes one guessed it, and
	# the guess may match the unconfirmed figure exactly. One withheld on a row
	# the model cited is refused outright; one withheld elsewhere is refused
	# unless the row the claim resolves to confirms it.
	withheld_cited = _withheld_values(cited or [])
	withheld = _withheld_values(rows)
	order = list(cited or []) + [row for row in rows if row not in (cited or [])]
	supports = [_supported_values([row], []) for row in order]
	labels = [_values([public_label(row)]) for row in order]
	used: list[dict] = []
	# The rows the previous claim resolved to. Prose carries its subject on:
	# after "6\" Class 300:" (or "### 6\" Class 300", or "The Class 300
	# flange has a PCD of 269.9 mm."), "PCD 241.3 mm" or "It takes 8 bolts"
	# is read as Class 300's. So a claim must resolve within the rows the one
	# before it did, unless it names another row by a label figure the current
	# rows do not share (150 against 300; not the 6 both are). A blank line
	# does not start afresh: markdown puts one between a heading and its body,
	# and a new paragraph about another row names that row.
	context: set[int] | None = None
	for claim in _CLAIM.split(answer or ""):
		figures = numbers(claim)
		if figures:
			guessed = [v for v in figures if v & withheld_cited]
			if guessed:
				return None, [min(v) for v in guessed]
			holders = [j for j in range(len(order)) if all(v & supports[j] for v in figures)]
			if context:
				shared = set.intersection(*(labels[j] for j in context))
				named = [j for j in holders if any(v & labels[j] and not v & shared for v in figures)]
				holders = named or [j for j in holders if j in context]
			if holders:
				if order[holders[0]] not in used:
					used.append(order[holders[0]])
				context = set(holders)
			elif any(v & allowed for allowed in supports for v in figures):
				# on a row, but not on one this claim may be read as: a bolt set
				# no row holds, or a line read under another row's heading
				return None, [min(v) for v in figures if not any(v & allowed for allowed in supports)] or [
					min(figures[0])
				]
			else:
				# a claim no row touches: only an article in the prompt may carry it
				unsupported = [v for v in figures if not v & extra or v & withheld]
				if unsupported:
					return None, [min(v) for v in unsupported]
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
	r"\s*\([^()]*\bR\d{1,2}\b[^()]*\)|\b(?:see\s+|per\s+|from\s+)?(?:rows?\s+)?R\d{1,2}\b(?!\w)", re.I
)


def strip_row_ids(answer: str) -> str:
	"""``answer`` without the prompt's row ids, which mean nothing to a rep."""
	text = _ROW_REF.sub("", answer or "")
	text = re.sub(r"[ \t]+([.,;:])", r"\1", text)
	text = re.sub(r"[,;:]+(?=[.!?]|\s*$)", "", text)
	return re.sub(r"[ \t]{2,}", " ", text).strip()


# --- the deterministic answer --------------------------------------------------


def fallback_answer(entries: list[dict]) -> str:
	"""The rows themselves, as plain text: always exactly what the sheet says."""
	blocks = []
	for entry in entries[:FALLBACK_ROWS]:
		lines = [f"{public_label(entry)} ({entry.get('sheet_title', '')}, page {entry.get('page', '')})"]
		lines.extend(_cell_line(cell) for cell in entry.get("cells") or [])
		blocks.append("\n".join(lines))
	heading = "Here is what the sheet says:" if len(blocks) == 1 else "These rows on the sheets match:"
	return heading + "\n\n" + "\n\n".join(blocks)


def public_cell(cell: dict) -> dict:
	"""A cell as it may leave the server: a questioned value and its note are withheld."""
	shown = {key: cell.get(key) for key in ("label", "value", "unit", "status", "note", "bbox")}
	if cell.get("status") == QUESTIONED:
		# the note may carry the figure the company was asked about ("should it
		# be 26.0?"), which is no more confirmed than the value
		shown["value"] = ""
		shown["note"] = ""
	return shown
