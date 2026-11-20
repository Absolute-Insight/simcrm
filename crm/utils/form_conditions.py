"""A public form's field conditions, evaluated on the server exactly as the page does.

The branded page (crm/www/crm_form.html, between its `[conditional-eval]` markers)
hides fields by `depends_on`, requires them by `reqd` or `mandatory_depends_on`
and exempts them by `read_only_depends_on`, all in the browser. Frappe's `accept()`
enforces a plain `reqd` and nothing else, so a submission posted straight to it
could skip a "required if" answer or fill a field the page would have hidden.

This is a port of that evaluator with JavaScript's semantics -- loose `==`,
relational coercion, truthiness -- because the two must agree on every input: a
condition the page treats as met has to be met here too, or a visitor who filled
in the form correctly is refused. form_condition_cases.json is run against both.

Expressions are parsed, never executed: `doc`/`parent` member access, literals,
comparisons, && || ! and parentheses. Anything else raises, and the caller's
fallback applies, as on the page.
"""

import math
import re

BREAKS = ("Section Break", "Column Break", "Tab Break")

# JavaScript's \s, which is what the page's ws() skips and String.trim() drops.
_JS_SPACE = (
	"\t\n\v\f\r              "
	"    　﻿"
)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?", re.ASCII)
_NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_OPERATORS = ("===", "!==", "==", "!=", "<=", ">=", "<", ">")
_JS_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)", re.ASCII)
_JS_RADIX = {"0x": 16, "0o": 8, "0b": 2}


class _Undefined:
	"""JavaScript's `undefined`: what a missing key or member reads as."""

	def __repr__(self):
		return "undefined"


UNDEFINED = _Undefined()


class _Unsupported(Exception):
	pass


# ---- JavaScript value semantics -------------------------------------------------


def js_truthy(value) -> bool:
	"""The page's coerce(): an array by its length, anything else by `!!value`."""
	if value is None or value is UNDEFINED:
		return False
	if isinstance(value, bool):
		return value
	if isinstance(value, int | float):
		return value != 0 and not math.isnan(value)
	if isinstance(value, str | list | tuple):
		return len(value) > 0
	return True  # an object, even an empty one


def _to_number(value) -> float:
	"""JavaScript's Number(value) for the primitives a form holds."""
	if value is None:
		return 0.0
	if value is UNDEFINED:
		return math.nan
	if isinstance(value, bool):
		return float(value)
	if isinstance(value, int | float):
		return float(value)
	if isinstance(value, str):
		s = value.strip(_JS_SPACE)
		if not s:
			return 0.0
		if _JS_DECIMAL.fullmatch(s):
			return float(s)
		if s in ("Infinity", "+Infinity"):
			return math.inf
		if s == "-Infinity":
			return -math.inf
		radix = _JS_RADIX.get(s[:2].lower())
		if radix:
			try:
				return float(int(s[2:], radix))
			except ValueError:
				return math.nan
		return math.nan
	if isinstance(value, list | tuple):
		# [] -> "" -> 0, [x] -> String(x), longer -> "a,b" -> NaN
		if not value:
			return 0.0
		if len(value) == 1:
			return _to_number(_to_string(value[0]))
		return math.nan
	return math.nan


def _to_string(value) -> str:
	if value is None:
		return "null"
	if value is UNDEFINED:
		return "undefined"
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, float):
		if math.isnan(value):
			return "NaN"
		if math.isinf(value):
			return "Infinity" if value > 0 else "-Infinity"
		if value.is_integer() and abs(value) < 1e21:
			return str(int(value))
		return repr(value)
	if isinstance(value, int):
		return str(value)
	if isinstance(value, str):
		return value
	if isinstance(value, list | tuple):
		return ",".join("" if v is None or v is UNDEFINED else _to_string(v) for v in value)
	return "[object Object]"


def _is_object(value) -> bool:
	return isinstance(value, list | tuple | dict)


def _to_primitive(value):
	# an array compares by its String(); a plain object by "[object Object]"
	return _to_string(value) if _is_object(value) else value


def _loose_equal(a, b) -> bool:
	"""JavaScript's `==` (Abstract Equality), for the values a form holds."""
	a_nullish = a is None or a is UNDEFINED
	b_nullish = b is None or b is UNDEFINED
	if a_nullish or b_nullish:
		return a_nullish and b_nullish
	if _is_object(a) and _is_object(b):
		return a is b
	a, b = _to_primitive(a), _to_primitive(b)
	if isinstance(a, str) and isinstance(b, str):
		return a == b
	if isinstance(a, bool) and isinstance(b, bool):
		return a == b
	left, right = _to_number(a), _to_number(b)
	return left == right  # NaN is never equal, as in JavaScript


def _relational(op: str, a, b) -> bool:
	"""JavaScript's < <= > >=: strings compare as strings, anything else as numbers."""
	a, b = _to_primitive(a), _to_primitive(b)
	if isinstance(a, str) and isinstance(b, str):
		# UTF-16 code units, as JavaScript compares them
		left, right = a.encode("utf-16-be"), b.encode("utf-16-be")
	else:
		left, right = _to_number(a), _to_number(b)
		if math.isnan(left) or math.isnan(right):
			return False
	if op == "<":
		return left < right
	if op == "<=":
		return left <= right
	if op == ">":
		return left > right
	return left >= right


def _member(base, key):
	"""`base[key]` / `base.key`, for the values a form holds. A null base reads as
	undefined rather than throwing -- the page does the same."""
	if base is None or base is UNDEFINED:
		return UNDEFINED
	name = _to_string(key)
	if isinstance(base, dict):
		return base.get(name, UNDEFINED)
	if isinstance(base, str | list | tuple):
		if name == "length":
			return len(base.encode("utf-16-be")) // 2 if isinstance(base, str) else len(base)
		if name.isdigit() and (name == "0" or not name.startswith("0")):
			index = int(name)
			if isinstance(base, list | tuple):
				return base[index] if index < len(base) else UNDEFINED
			units = base.encode("utf-16-be")
			if index < len(units) // 2:
				return units[index * 2 : index * 2 + 2].decode("utf-16-be", errors="replace")
	return UNDEFINED


# ---- the parser (mirrors safeEval in crm_form.html) -----------------------------


class _Parser:
	def __init__(self, src: str, doc):
		self.src, self.i, self.doc = src, 0, doc

	def ws(self):
		while self.i < len(self.src) and self.src[self.i] in _JS_SPACE:
			self.i += 1

	def starts(self, token: str) -> bool:
		self.ws()
		return self.src.startswith(token, self.i)

	def parse(self):
		out = self.or_expr()
		self.ws()
		if self.i < len(self.src):
			raise _Unsupported("trailing input")
		return out

	def or_expr(self):
		left = self.and_expr()
		while self.starts("||"):
			self.i += 2
			right = self.and_expr()
			left = js_truthy(left) or js_truthy(right)
		return left

	def and_expr(self):
		left = self.comparison()
		while self.starts("&&"):
			self.i += 2
			right = self.comparison()
			left = js_truthy(left) and js_truthy(right)
		return left

	def comparison(self):
		left = self.primary()
		self.ws()
		for op in _OPERATORS:
			if self.src.startswith(op, self.i):
				self.i += len(op)
				right = self.primary()
				if op in ("===", "=="):
					return _loose_equal(left, right)
				if op in ("!==", "!="):
					return not _loose_equal(left, right)
				return _relational(op, left, right)
		return left

	def primary(self):
		self.ws()
		if self.starts("("):
			self.i += 1
			value = self.or_expr()
			if not self.starts(")"):
				raise _Unsupported("expected )")
			self.i += 1
			return value
		if self.starts("!"):
			self.i += 1
			return not js_truthy(self.primary())
		if self.i >= len(self.src):
			raise _Unsupported("unexpected end")
		quote = self.src[self.i]
		if quote in ("'", '"'):
			return self.string(quote)
		if number := _NUMBER.match(self.src, self.i):
			self.i = number.end()
			return float(number.group())
		name = _NAME.match(self.src, self.i)
		if not name:
			raise _Unsupported("unexpected token")
		self.i = name.end()
		word = name.group()
		if word == "true":
			return True
		if word == "false":
			return False
		if word == "null":
			return None
		if word not in ("doc", "parent"):
			raise _Unsupported("unknown identifier")  # no globals reachable
		return self.members(self.doc)

	def string(self, quote: str) -> str:
		# the page's loop: a backslash takes the next character literally, and an
		# unterminated string runs to the end of the source
		self.i += 1
		out = []
		while self.i < len(self.src) and self.src[self.i] != quote:
			if self.src[self.i] == "\\":
				self.i += 1
			if self.i < len(self.src):
				out.append(self.src[self.i])
			else:
				out.append("undefined")  # src[i] past the end, concatenated by the page
			self.i += 1
		self.i += 1
		return "".join(out)

	def members(self, base):
		while True:
			self.ws()
			if self.src.startswith(".", self.i):
				self.i += 1
				name = _NAME.match(self.src, self.i)
				if not name:
					raise _Unsupported("bad member")
				self.i = name.end()
				base = _member(base, name.group())
			elif self.src.startswith("[", self.i):
				self.i += 1
				key = self.or_expr()
				if not self.starts("]"):
					raise _Unsupported("expected ]")
				self.i += 1
				base = _member(base, key)
			else:
				return base


def truthy(expr, doc: dict, fallback: bool) -> bool:
	"""The page's truthy(): an `eval:` expression, `fn:` (never run), or a fieldname
	whose value must be set. An empty, unsupported or invalid expression returns
	`fallback`."""
	s = str(expr).strip(_JS_SPACE) if expr else ""
	if not s:
		return fallback
	try:
		if s.startswith("eval:"):
			return js_truthy(_Parser(s[5:], doc).parse())
		if s.startswith("fn:"):
			return fallback
		return js_truthy(_member(doc, s))
	except (_Unsupported, RecursionError):
		return fallback


# ---- what the page does with them ------------------------------------------------


def _get(f, key):
	# a dict, a frappe._dict or a Web Form Field row: all answer .get()
	return f.get(key)


def is_visible(f, doc: dict) -> bool:
	return truthy(_get(f, "depends_on"), doc, True)


def is_required(f, doc: dict) -> bool:
	return bool(_get(f, "reqd")) or truthy(_get(f, "mandatory_depends_on"), doc, False)


def is_read_only(f, doc: dict) -> bool:
	return truthy(_get(f, "read_only_depends_on"), doc, False)


def _is_empty(fieldtype: str, value) -> bool:
	# a Check must be ticked; anything else must not be "" (an input's empty value)
	if fieldtype == "Check":
		return not js_truthy(value) or value == "0"
	return value is None or value == ""


def _is_field(f) -> bool:
	return bool(_get(f, "fieldname")) and _get(f, "fieldtype") not in BREAKS


def resolve_values(fields, values: dict) -> dict:
	"""The page's resolveDoc(): the values every condition reads. A field the form
	does not send reads as "" (what accept() stores for it), a hidden field counts as
	empty however it was left, and hiding one can hide others, so repeat until
	nothing changes. Values only ever move to "", so this ends within len(fields)
	passes."""
	doc = {}
	for f in fields:
		if _is_field(f):
			fieldname = _get(f, "fieldname")
			value = values.get(fieldname, "")
			doc[fieldname] = "" if value is UNDEFINED else value
	changed = True
	while changed:
		changed = False
		for f in fields:
			if not _is_field(f):
				continue
			fieldname = _get(f, "fieldname")
			if not (isinstance(doc[fieldname], str) and doc[fieldname] == "") and not is_visible(f, doc):
				doc[fieldname] = ""
				changed = True
	return doc


def review_submission(fields, values: dict) -> tuple[list[str], list]:
	"""The page's reviewSubmission(), applied to one submission.

	Returns (hidden, missing): the fieldnames the page would have hidden, and so not
	sent, and the field rows that are required while shown and editable, and empty
	-- in form order. Conditions read resolve_values(), as the page's do."""
	doc = resolve_values(fields, values)
	hidden, missing = [], []
	for f in fields:
		if not _is_field(f):
			continue
		fieldname = _get(f, "fieldname")
		if not is_visible(f, doc):
			hidden.append(fieldname)
			continue
		if is_required(f, doc) and not is_read_only(f, doc) and _is_empty(_get(f, "fieldtype"), doc[fieldname]):
			missing.append(f)
	return hidden, missing
