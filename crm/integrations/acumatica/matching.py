"""Pure helpers for the customer push: how a name, a VAT number and a province are
compared or spelled for Acumatica. No frappe imports, so they test as plain functions.

Duplicate detection compares a new organization against every customer already
synced from Acumatica (~1,100 on MBP's tenant), so these stay cheap: one
normalisation per name, and SequenceMatcher only behind its quick upper bounds.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Legal-form and filler tokens that say nothing about which business it is. "Holdings"
# is here because "Bearing Man Holdings" and "Bearing Man" are one group to a sales
# office; "group" is not, it is too often the distinguishing word.
_FORM_TOKENS = frozenset(
	{
		"pty",
		"pty.",
		"ltd",
		"limited",
		"proprietary",
		"cc",
		"inc",
		"incorporated",
		"co",
		"company",
		"plc",
		"holding",
		"holdings",
		"the",
	}
)
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")

# Fuzzy threshold on the token-sorted names. 0.9 keeps "Acme Engineering" from
# matching "Acme Engineers", which are different MBP customers more often than not.
SIMILARITY_THRESHOLD = 0.9


def normalise_name(name: str) -> str:
	"""A customer name reduced to the words that identify the business.

	casefold, "&" -> "and", punctuation dropped, legal-form tokens dropped, a trailing
	"cod" (payment terms leaking into the name, as in "Acme - COD") dropped."""
	text = (name or "").casefold().replace("&", " and ")
	text = _PUNCT.sub(" ", text)
	tokens = [t for t in _SPACE.split(text) if t and t not in _FORM_TOKENS]
	while tokens and tokens[-1] == "cod":
		tokens.pop()
	return " ".join(tokens)


def _sorted_tokens(normalised: str) -> str:
	return " ".join(sorted(normalised.split()))


def name_match(a: str, b: str) -> str | None:
	"""Why two *normalised* names look like one business -- "same name",
	"similar name" -- or None.

	Besides equality and a token-sorted similarity of SIMILARITY_THRESHOLD, a name
	whose words are all inside the other's (at least two of them) counts as similar:
	"Bearing Man Group - Mozambique" may well be a second account of "Bearing Man
	Group", and asking a manager costs one click where a silent duplicate costs the
	accounts department an afternoon."""
	if not a or not b:
		return None
	if a == b:
		return "same name"
	sa, sb = _sorted_tokens(a), _sorted_tokens(b)
	if sa == sb:
		return "same name"
	ta, tb = set(a.split()), set(b.split())
	small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
	if len(small) >= 2 and small < large and sum(len(t) for t in small) >= 6:
		return "similar name"
	matcher = SequenceMatcher(None, sa, sb, autojunk=False)
	if (
		matcher.real_quick_ratio() >= SIMILARITY_THRESHOLD
		and matcher.quick_ratio() >= SIMILARITY_THRESHOLD
		and matcher.ratio() >= SIMILARITY_THRESHOLD
	):
		return "similar name"
	return None


def normalise_vat(value) -> str:
	"""Digits only, or "" for anything too short to identify a taxpayer. A ZA VAT
	number is ten digits; people type it with spaces, dashes or a "VAT" prefix."""
	digits = re.sub(r"\D", "", str(value or ""))
	return digits if len(digits) >= 5 else ""


# South African provinces as MBP's tenant codes them.
ZA_PROVINCES = {
	"GP": ("gauteng",),
	"NW": ("north west", "northwest", "north west province"),
	"MP": ("mpumalanga",),
	"LP": ("limpopo", "northern province"),
	"KZN": ("kwazulu natal", "kwazulunatal", "kzn", "natal"),
	"WC": ("western cape",),
	"FS": ("free state", "orange free state"),
	"EC": ("eastern cape",),
	"NC": ("northern cape",),
}
_ZA_LOOKUP = {name: code for code, names in ZA_PROVINCES.items() for name in names}
_ZA_LOOKUP.update({code.casefold(): code for code in ZA_PROVINCES})
_SHORT_CODE = re.compile(r"^[A-Za-z0-9]{1,3}$")


def state_code(state, country_code) -> str | None:
	"""The State value Acumatica expects, or None to leave it out.

	For South Africa a province name in any of the spellings people type --
	"Gauteng", "GAUTENG", "GP - Gauteng", "KwaZulu-Natal", "North-West Province" --
	becomes its code. Elsewhere a value is only sent if it already looks like a code
	(three letters or digits at most): Acumatica validates State against its own
	list for the country, and a full name it does not know fails the whole PUT."""
	raw = (state or "").strip()
	if not raw:
		return None
	if (country_code or "").upper() == "ZA":
		text = _SPACE.sub(" ", _PUNCT.sub(" ", raw.casefold())).strip()
		candidates = [text, text.removesuffix(" province").strip()]
		# "GP - Gauteng" / "Gauteng (GP)": try each half
		parts = [p.strip() for p in re.split(r"\s-\s|[()/]", raw.casefold()) if p.strip()]
		candidates += [_SPACE.sub(" ", _PUNCT.sub(" ", p)).strip() for p in parts]
		for c in candidates:
			if c in _ZA_LOOKUP:
				return _ZA_LOOKUP[c]
			if c.replace(" ", "") in _ZA_LOOKUP:
				return _ZA_LOOKUP[c.replace(" ", "")]
		return None
	return raw.upper() if _SHORT_CODE.match(raw) else None
