"""Close a way round every document's ``validate``.

frappe keeps ``_action`` out of nothing: it is not in ``RESERVED_KEYWORDS``, so a
request can set it, and ``Document._save`` skips ``validate``, ``before_save`` and
``on_update`` when it reads "discard", along with the docstatus transition check.
``PUT /api/resource/CRM Deal/<own deal>`` with ``{"_action": "discard", ...}`` wrote
any field past every rule in this app.

A genuine discard is ``Document.discard()``, which runs ``before_discard`` first; a
request cannot set ``flags``, so that mark tells the two apart. ``docstatus`` cannot:
a request can send that too. Remove this once the frappe pin reserves ``_action``.
"""

import frappe
from frappe import _


def mark_real_discard(doc, method=None) -> None:
	doc.flags.in_discard = True


def refuse_forged_discard(doc, method=None) -> None:
	"""``on_change`` still runs on the skipped path, and raising rolls the save back."""
	if doc.get("_action") == "discard" and not doc.flags.in_discard:
		frappe.throw(_("This save was refused: it asked to skip validation."), frappe.PermissionError)
