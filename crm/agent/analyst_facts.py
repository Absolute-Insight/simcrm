# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the Analyst may say about its tables, worked out by code, and a check on
what it did say. Pure: tables in, lines out. No frappe.

The answer prompt has always said "every number must come from the figures".
On 2026-10-15 a 2.6B model on a live site was handed correct tables and still:

- refused "how much did we win last quarter?" a total, because the prompt also
  says not to add rows up -- then called the quarter it *had* been given missing;
- named January the peak month (February was) and an eighteen-day-old October
  a 100% collapse;
- put one rep's deal count and value under another rep's name;
- quoted 16,103,914.09 for a month whose row says 16,103,594.09.

So the arithmetic a question needs -- totals, quarters, best and worst month,
rankings -- is done here and handed to the model as lines it may quote
(:func:`table_facts`), the highlights shown on screen are those lines rather
than the model's restatement of them (:func:`highlights`), and every sentence
the model writes is checked against the tables before an admin reads it
(:func:`ground_reply`). A sentence whose number is in no table, whose number
belongs to someone it does not name, that calls a period the tables cover
missing, or that leaks the prompt's own vocabulary is dropped, not repaired:
the screen still shows every table, so a dropped sentence loses words, never
data.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from crm.agent import analyst

MAX_HIGHLIGHTS = 5
RANK_TOP = 5

# What the answer becomes when nothing the model wrote survived the check.
FALLBACK_ANSWER = "Vectora could not put this into words reliably. The figures it computed are shown below."

# Monthly series: catalogue key -> (row field, what the value is called).
_MONTHLY = {
	"won_revenue_by_month": [("value", "Won")],
	"growth_rates": [("value", "Won")],
	"forecast_by_month": [("value", "Weighted pipeline")],
	"erp_invoices_by_month": [("invoiced", "Invoiced")],
	"erp_payments_by_month": [("received", "Received")],
	"erp_cashflow_by_month": [("invoiced", "Invoiced"), ("received", "Received")],
}
# Months that are still to come: no "month to date", no worst month.
_FORWARD = {"forecast_by_month"}

# Rankings: catalogue key -> (label field, value field, what the value is, money?).
_RANKED = {
	"quota_attainment_by_rep": ("rep", "actual", "won value", True),
	"deals_by_salesperson": ("salesperson", "value", "deal value", True),
	"deals_by_industry": ("industry", "value", "deal value", True),
	"deals_by_territory": ("territory", "value", "deal value", True),
	"leads_by_source": ("source", "count", "leads", False),
}

# Fact lines that quote one row's own figure -- a best or worst month, a ranking,
# the largest deals at risk, the busiest month -- rather than a sum over the
# table. Grounding leaves their numbers to the row that owns them: read as totals,
# which may stand beside any name, they let one rep's value through under another
# rep's name -- the very misattribution the check exists to catch.
_ROW_FACTS = ("Highest month:", "Lowest month:", "Ranked by ", "Largest at risk:", "Most new deals:")


# --- facts -------------------------------------------------------------------


def table_facts(table: dict, today: date) -> list[str]:
	"""Plain-language lines carrying the arithmetic a question about ``table`` needs."""
	rows = table.get("rows") or []
	if table.get("error") or not rows:
		return []
	key = table.get("key")
	if key in _MONTHLY:
		lines = []
		for field, label in _MONTHLY[key]:
			lines.extend(_monthly_facts(rows, field, label, today, forward=key in _FORWARD))
		return lines
	if key in _RANKED:
		return _ranked_facts(key, rows)
	if key == "pipeline_by_stage":
		return _pipeline_facts(rows)
	if key == "sales_trend":
		return _trend_facts(rows)
	if key == "deals_at_risk":
		return _at_risk_facts(rows)
	return []


def highlights(tables: list[dict]) -> list[str]:
	"""The lines shown as bullets: computed facts, in plan order."""
	lines: list[str] = []
	for table in tables:
		for line in table.get("facts") or []:
			if line not in lines:
				lines.append(line)
	return lines[:MAX_HIGHLIGHTS]


def _money(value: float) -> str:
	return f"{round(value):,}"


def _monthly_facts(rows, field, label, today, forward=False) -> list[str]:
	series = [(row["month"], float(row.get(field) or 0)) for row in rows if row.get("month")]
	if not series:
		return []
	current = analyst.month_key(today)
	first, last = series[0][0], series[-1][0]
	total = sum(value for _month, value in series)
	partial = not forward and any(month == current for month, _value in series)

	quarters = _quarters(series, current, forward)
	lines: list[str] = []
	only = len(quarters) == 1 and quarters[0][2] == len(series) and not quarters[0][3]
	if only:
		name, value, _count, _to_date = quarters[0]
		lines.append(
			f"{name} ({calendar.month_name[int(first[5:])]} to {analyst.month_label(last)}): {_money(value)}"
		)
	else:
		line = f"{label} total, {analyst.month_label(first)} to {analyst.month_label(last)}: {_money(total)}"
		if partial:
			line += f" ({analyst.month_label(current)} is month to date)"
		lines.append(line)

	best, worst = _extremes(series, current, forward)
	if best:
		lines.append(f"Highest month: {analyst.month_label(best[0])} ({_money(best[1])})")
	if worst:
		lines.append(f"Lowest month: {analyst.month_label(worst[0])} ({_money(worst[1])})")

	if not only:
		for name, value, _count, to_date in quarters:
			lines.append(f"{name}{' to date' if to_date else ''}: {_money(value)}")
	return lines


def _extremes(series, current, forward=False):
	"""``(best, worst)`` months as ``(month, value)``, or ``None`` each.

	Over whole months since revenue began: the current month is days old, and the
	months before the first sale are unknown, not bad. A forward series has no
	worst month worth naming -- its far months are simply not booked yet.
	"""
	whole = [(month, value) for month, value in series if forward or month < current]
	while whole and not whole[0][1] and not forward:
		whole.pop(0)
	if len(whole) < 2:
		return None, None
	best = max(whole, key=lambda item: item[1])
	return best, None if forward else min(whole, key=lambda item: item[1])


def _quarters(series, current, forward) -> list[tuple[str, float, int, bool]]:
	"""``(name, total, months, to_date)`` for each quarter the series holds whole,
	plus the current quarter so far. A quarter the window only clips is left out:
	its total would be a part passed off as the whole."""
	by_quarter: dict[tuple[int, int], list[tuple[str, float]]] = {}
	for month, value in series:
		year, number = int(month[:4]), int(month[5:])
		by_quarter.setdefault((year, (number - 1) // 3 + 1), []).append((month, value))
	out = []
	for (year, quarter), months in by_quarter.items():
		wanted = [f"{year:04d}-{(quarter - 1) * 3 + step:02d}" for step in (1, 2, 3)]
		present = [month for month, _value in months]
		value = sum(v for _month, v in months)
		name = f"Q{quarter} {year}"
		if not forward and current in wanted:
			# so far: every month from the quarter's first up to this one
			if present == [m for m in wanted if m <= current]:
				out.append((name, value, len(months), True))
		elif present == wanted:
			out.append((name, value, 3, False))
	return out


def _ranked_facts(key, rows) -> list[str]:
	label_field, value_field, what, money = _RANKED[key]
	ranked = sorted(
		(row for row in rows if row.get(value_field) is not None),
		key=lambda row: -float(row.get(value_field) or 0),
	)
	if not ranked:
		return []
	show = _money if money else (lambda value: f"{int(value):,}")
	entries = "; ".join(
		f"{place}. {row.get(label_field)} {show(float(row[value_field]))}"
		for place, row in enumerate(ranked[:RANK_TOP], 1)
	)
	lines = [f"Ranked by {what}: {entries}"]
	if len(ranked) > RANK_TOP:
		lines[0] += f" ({len(ranked) - RANK_TOP} more not shown)"
	lines.append(f"Total {what}: {show(sum(float(row[value_field]) for row in ranked))}")
	if key == "quota_attainment_by_rep" and not any(float(row.get("quota") or 0) for row in rows):
		lines.append("No rep has a target set for this period, so attainment cannot be measured.")
	return lines


def _pipeline_facts(rows) -> list[str]:
	deals = sum(int(row.get("deals") or 0) for row in rows)
	value = sum(float(row.get("value") or 0) for row in rows)
	weighted = sum(float(row.get("weighted") or 0) for row in rows)
	line = f"{deals} open deals worth {_money(value)}"
	if value:
		line += (
			f"; weighted by stage probability that is {_money(weighted)} "
			f"({round(weighted / value * 100)}% of the value)"
		)
	return [line]


def _trend_facts(rows) -> list[str]:
	totals = {key: sum(int(row.get(key) or 0) for row in rows) for key in ("leads", "deals", "won_deals")}
	lines = [
		f"Totals: {totals['leads']:,} new leads, {totals['deals']:,} new deals, {totals['won_deals']:,} deals won"
	]
	if len(rows) >= 2:
		busiest = max(rows, key=lambda row: int(row.get("deals") or 0))
		lines.append(
			f"Most new deals: {analyst.month_label(busiest['month'])} ({int(busiest.get('deals') or 0):,})"
		)
	return lines


def _at_risk_facts(rows) -> list[str]:
	total = sum(float(row.get("value") or 0) for row in rows)
	lines = [f"{len(rows):,} deals at risk worth {_money(total)}"]
	largest = sorted(rows, key=lambda row: -float(row.get("value") or 0))[:3]
	lines.append(
		"Largest at risk: "
		+ "; ".join(
			f"{row.get('organization') or row.get('deal')} {_money(float(row.get('value') or 0))}"
			for row in largest
		)
	)
	return lines


# --- coverage ----------------------------------------------------------------


def trim_to_coverage(rows: list[dict], data_from: str | None) -> tuple[list[dict], str]:
	"""Rows for months before the site's history begins, removed, and a note saying why.

	Imported history starts somewhere. A month before it is unknown, and a table
	that shows it as 0 gets read as "no sales that year" -- which is what an admin
	was told about 2024 on a site whose data begins in December 2025.
	"""
	if not data_from:
		return rows, ""
	kept = [row for row in rows if not row.get("month") or row["month"] >= data_from]
	if len(kept) == len(rows):
		return rows, ""
	return kept, analyst.coverage_line(data_from)


# --- grounding ---------------------------------------------------------------

# A number as a person writes one: 18,534,521 / 18534520.84 / 18.5 million.
_NUMBER = re.compile(
	r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*(million|mn|m|billion|bn|thousand|k)\b)?",
	re.IGNORECASE,
)
_SCALE = {"million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}
_PERCENT_AFTER = re.compile(r"\s*(?:%|per\s?cent\b)", re.IGNORECASE)
# Things with digits in them that are names, not figures.
_MASKED = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d{4}-\d+\b|\b\d{4}-\d{2}(?:-\d{2})?\b|\bQ[1-4]\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_QUARTER = re.compile(r"\bQ([1-4])\s*(\d{4})\b", re.IGNORECASE)
_MISSING = re.compile(
	r"not available|unavailable|missing|no data|not (?:provided|included|shown|present|covered)|"
	r"(?:does|do) not (?:include|cover|contain|show)",
	re.IGNORECASE,
)
_BEST = re.compile(r"\b(?:peak|peaked|highest|best|strongest|record|biggest)\b", re.IGNORECASE)
_WORST = re.compile(r"\b(?:lowest|worst|weakest|slowest|smallest)\b", re.IGNORECASE)
_CHANGE = re.compile(
	r"%|\b(?:decrease|decline|drop|dropped|fell|fall|collapse|plunge)\b|(?<!break )\bdown\b", re.IGNORECASE
)
# "no data before December 2025" names a covered month to say what is *not* covered
_BEFORE = re.compile(r"\b(?:before|prior to|earlier than)\b", re.IGNORECASE)
_ERP_WORDS = re.compile(r"invoice|payment|cash|receivable|\berp\b|acumatica|erpnext", re.IGNORECASE)
# The prompt's own vocabulary and raw field names: never for an admin's eyes. The
# fence's name is matched in capitals only -- "the figures show" is plain English.
_JARGON = re.compile(r"figures block|\bjson\b|\b\w+_(?:pct|id|key)\b|\bnull\b", re.IGNORECASE)
_FENCE_WORD = re.compile(r"\bFIGURES\b")
# Text columns that hold prose, not names.
_NOT_NAMES = {"reasons", "reason", "kind"}


def ground_reply(
	answer: str, caveats: list[str], tables: list[dict], today: date, history: list[dict] | None = None
) -> dict:
	"""``answer`` and ``caveats`` with every sentence the tables do not support removed.

	``history`` is the conversation so far. A follow-up ("and the quarter before?")
	is answered from this turn's tables but compares with a figure the last answer
	gave, so the numbers of earlier *answers* count as known. Not the admin's own
	turns: a number someone typed is a question, not a figure.

	Returns ``{"answer", "caveats", "dropped"}``; ``dropped`` counts sentences.
	"""
	index = _Index(tables, today)
	for turn in history or []:
		if isinstance(turn, dict) and turn.get("role") == "assistant":
			index.known.extend(_parse_numbers(_MASKED.sub(" ", str(turn.get("content") or ""))))
	kept, dropped = _keep(answer or "", index)
	out_caveats = []
	for caveat in caveats or []:
		text, lost = _keep(caveat, index)
		dropped += lost
		if text:
			out_caveats.append(text)
	return {"answer": kept or FALLBACK_ANSWER, "caveats": out_caveats, "dropped": dropped}


def _keep(text: str, index: _Index) -> tuple[str, int]:
	sentences = [part.strip() for part in _SENTENCE.split(text.strip()) if part.strip()]
	kept = [sentence for sentence in sentences if index.supports(sentence)]
	return " ".join(kept), len(sentences) - len(kept)


class _Index:
	"""Every number the tables hold, which named row owns which, and which months they cover."""

	def __init__(self, tables: list[dict], today: date):
		# (value, tolerance): a row's float is exact; a fact written "18,534,521" is good to 0.5
		self.known: list[tuple[float, float]] = []
		self.owned: dict[str, list[float]] = {}
		self.covered: set[str] = set()
		self.covered_years: set[str] = set()
		# totals: a count or sum over a table, owned by no row
		self.totals: list[float] = []
		self.erp_unavailable = False
		self.current = analyst.month_key(today)
		# the months a "best"/"worst" claim may name, one per monthly series
		self.best: set[str] = set()
		self.worst: set[str] = set()
		for table in tables:
			if table.get("error"):
				self.erp_unavailable = self.erp_unavailable or str(table.get("key", "")).startswith("erp_")
				continue
			for field, _label in _MONTHLY.get(table.get("key"), []):
				series = [
					(row["month"], float(row.get(field) or 0))
					for row in table.get("rows") or []
					if row.get("month")
				]
				best, worst = _extremes(series, self.current, table.get("key") in _FORWARD)
				self.best.update([best[0]] if best else [])
				self.worst.update([worst[0]] if worst else [])
			rows = table.get("rows") or []
			self.known.append((float(len(rows)), 0.0))
			self.covered_years.update(str(row["month"])[:4] for row in rows if row.get("month"))
			text_columns = [
				column["key"]
				for column in table.get("columns") or []
				if column.get("type") in ("text", "month") and column["key"] not in _NOT_NAMES
			]
			for row in rows:
				values = _row_numbers(row)
				self.known.extend((value, 0.0) for value in values)
				for column in text_columns:
					for name in _names_for(row.get(column), month=column == "month"):
						self.owned.setdefault(name, []).extend(values)
				if row.get("month"):
					self.covered.add(str(row["month"]))
			self.totals.append(float(len(rows)))
			for line in [*(table.get("facts") or []), *(table.get("summary") or []), table.get("note") or ""]:
				numbers = _parse_numbers(line)
				self.known.extend(numbers)
				owner = re.match(r"-\s*(.+?):", line)
				if owner:
					name = owner.group(1).strip().lower()
					self.owned.setdefault(name, []).extend(value for value, _tol in numbers)
				elif (line in (table.get("facts") or []) and not line.startswith(_ROW_FACTS)) or line == (
					table.get("summary") or [None]
				)[0]:
					# a total belongs to no one row, so it may stand beside any name
					self.totals.extend(value for value, _tol in numbers)
		# longest first, so "impala - shaft 12" is matched before "impala - shaft 1"
		self.names = sorted((name for name in self.owned if len(name) >= 3), key=len, reverse=True)

	def supports(self, sentence: str) -> bool:
		if _JARGON.search(sentence) or _FENCE_WORD.search(sentence):
			return False
		mentioned, masked = self._mentions(sentence)
		periods = self._periods(sentence)
		if (
			_MISSING.search(sentence)
			and not _BEFORE.search(sentence)
			and not (self.erp_unavailable and _ERP_WORDS.search(sentence))
		):
			if periods & self.covered and not self._uncovered_year(sentence):
				return False
		# "a peak in January" when February was: the number is January's, the claim is not
		if periods and _BEST.search(sentence) and self.best and not periods & self.best:
			return False
		if periods and _WORST.search(sentence) and self.worst and not periods & self.worst:
			return False
		# a change measured against a month that is days old is not a change
		if self.current in periods & self.covered and _CHANGE.search(sentence):
			return False
		for value, tolerance, percent in _figures(_MASKED.sub(" ", masked)):
			if _exempt(value, tolerance, percent):
				continue
			if not any(_close(value, tolerance, known, slack) for known, slack in self.known):
				return False
			is_total = any(_close(value, tolerance, total, 0.5) for total in self.totals)
			if (
				mentioned
				and not is_total
				and not any(self._owns(name, value, tolerance) for name in mentioned)
			):
				# a figure that belongs to a row this sentence does not name
				if any(self._owns(name, value, tolerance) for name in self.owned if name not in mentioned):
					return False
		return True

	def _owns(self, name: str, value: float, tolerance: float) -> bool:
		return any(_close(value, tolerance, known, 0.0) for known in self.owned.get(name, []))

	def _mentions(self, sentence: str) -> tuple[set[str], str]:
		"""Names of rows the sentence mentions, and the sentence with them blanked out
		so the digits inside a name ("Shaft 12", "C-SIB001F") are not read as figures."""
		lowered = sentence.lower()
		masked = list(sentence)
		found = set()
		for name in self.names:
			for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", lowered):
				if all(masked[i] != "\0" for i in range(match.start(), match.end())):
					found.add(name)
					for i in range(match.start(), match.end()):
						masked[i] = "\0"
		return found, "".join(" " if ch == "\0" else ch for ch in masked)

	def _uncovered_year(self, sentence: str) -> bool:
		"""Whether the sentence names a year the tables hold no month of -- the
		thing it is saying is missing, beside a covered month it names for contrast."""
		bare = _MASKED.sub(" ", re.sub(r"\b[A-Za-z]+\s+\d{4}\b", " ", sentence))
		return any(year not in self.covered_years for year in re.findall(r"\b(?:19|20)\d{2}\b", bare))

	def _periods(self, sentence: str) -> set[str]:
		months = set()
		for month_number in range(1, 13):
			full, short = calendar.month_name[month_number], calendar.month_abbr[month_number]
			for match in re.finditer(rf"\b(?:{full}|{short})\s+(\d{{4}})\b", sentence, re.IGNORECASE):
				months.add(f"{match.group(1)}-{month_number:02d}")
		for match in re.finditer(r"\b(\d{4})-(\d{2})\b", sentence):
			months.add(f"{match.group(1)}-{match.group(2)}")
		for match in _QUARTER.finditer(sentence):
			quarter, year = int(match.group(1)), match.group(2)
			months.update(f"{year}-{(quarter - 1) * 3 + step:02d}" for step in (1, 2, 3))
		return months


def _names_for(value, month: bool = False) -> list[str]:
	if value is None or value == "":
		return []
	text = str(value).strip()
	if not month:
		return [text.lower()] if len(text) <= 80 else []
	try:
		year, number = int(text[:4]), int(text[5:7])
	except ValueError:
		return []
	return [
		text.lower(),
		f"{calendar.month_name[number]} {year}".lower(),
		f"{calendar.month_abbr[number]} {year}".lower(),
	]


def _row_numbers(row: dict) -> list[float]:
	"""The figures in a row: its numbers, and those inside its prose ("No activity for
	239 days") -- never the digits of a name ("Impala - Shaft 12", "Karee 3")."""
	values = []
	for key, value in row.items():
		if isinstance(value, bool):
			continue
		if isinstance(value, int | float):
			values.append(float(value))
		elif isinstance(value, str) and key in _NOT_NAMES:
			values.extend(number for number, _tol in _parse_numbers(_MASKED.sub(" ", value)))
	return values


def _parse_numbers(text: str) -> list[tuple[float, float]]:
	"""``(value, tolerance)`` for each number in ``text``: the half-unit of its last digit."""
	return [(value, tolerance) for value, tolerance, _percent in _figures(text)]


def _figures(text: str) -> list[tuple[float, float, bool]]:
	"""``(value, tolerance, percent)`` for each number in ``text``; ``percent`` when a
	``%`` or "percent" follows it."""
	out = []
	for match in _NUMBER.finditer(text or ""):
		whole, fraction, scale = match.group(1), match.group(2) or "", match.group(3)
		value = float(whole.replace(",", "") + fraction)
		places = len(fraction) - 1 if fraction else 0
		tolerance = 0.5 * 10 ** (-places)
		if scale:
			factor = _SCALE[scale.lower()]
			value, tolerance = value * factor, tolerance * factor
		out.append((value, tolerance, bool(_PERCENT_AFTER.match(text, match.end()))))
	return out


def _close(value: float, tolerance: float, known: float, slack: float) -> bool:
	# a change is written "fell 43.4%" as often as "-43.4%"
	return abs(abs(value) - abs(known)) <= max(tolerance, slack) + 1e-9


def _exempt(value: float, tolerance: float, percent: bool = False) -> bool:
	"""Years, days, months, quarters and small counts are not figures worth checking.

	A percentage is none of those, whatever its size: growth, attainment and
	adherence are written "25%", and a wrong one is as wrong as a wrong total.
	"""
	if tolerance < 0.5 or percent:
		return False
	return value <= 31 or (1900 <= value <= 2100 and value == int(value))
