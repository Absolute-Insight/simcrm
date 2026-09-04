"""Account-name normalisation shared by the spreadsheet import and the live sync.

Both must normalise a customer's display name identically. The spreadsheet import
has no Acumatica NoteID to key on, so it adopts pre-existing CRM Organization rows
by exact name match; if the two normalised names ever diverge, the live sync sees
an unfamiliar name for every row the import touched and creates a rival
organization instead of adopting the one already there.
"""

from __future__ import annotations

import re

# Payment terms leaking into the customer name. Only this suffix is stripped:
# "- Shaft 10", "- Driefontein Division" and the like are real delivery sites.
_COD_SUFFIX = re.compile(r"\s-\s[Cc][Oo][Dd]\s*$")


def normalise_account_name(name: str) -> str:
	return _COD_SUFFIX.sub("", (name or "").strip()).strip()
