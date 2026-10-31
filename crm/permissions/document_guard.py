"""Keep a request from choosing how a document is saved.

frappe does not reserve ``_action``, so a request can set it, and ``Document._save``
reads it: "discard" skips ``validate``, ``before_save`` and ``on_update`` and the
docstatus transition check, and on a Single any value does. ``PUT /api/resource/CRM
Deal/<own deal>`` with ``{"_action": "discard", ...}`` wrote any field past every
rule in this app.

Refusing it after the write does not hold, because ``frappe.client.bulk_update``
swallows the exception and commits. So it never reaches the document: both
``BaseDocument.update`` and ``set`` read this set at call time and drop what is in
it, and frappe itself only ever assigns the attribute.

Runs as ``before_request`` rather than at import, because hooks are served from
cache and ``hooks.py`` is not imported in every worker. Client input only arrives
in a request. Remove this once the frappe pin reserves ``_action``.
"""

from frappe.model import base_document


def reserve_action() -> None:
	if "_action" not in base_document.RESERVED_KEYWORDS:
		base_document.RESERVED_KEYWORDS = base_document.RESERVED_KEYWORDS | {"_action"}
