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

Runs as ``before_request`` and ``before_job`` rather than at import, because hooks
are served from cache and ``hooks.py`` is not imported in every process. Both,
because client data reaches workers too: frappe's bulk routes enqueue a large
request and apply it to documents there, as the user who sent it. Remove this once
the frappe pin reserves ``_action``.

It also calls engine_guard. That has its own hook entries, but a worker restarted
onto new code keeps the hook lists it cached under the old code until a migrate
clears them, and this function is already on those lists.
"""

# nosemgrep: frappe-semgrep-rules.rules.frappe-monkey-patching-not-allowed
from frappe.model import base_document


def reserve_action() -> None:
	from crm.permissions import engine_guard

	engine_guard.guard_request()
	if "_action" not in base_document.RESERVED_KEYWORDS:
		# No hook reaches this set, and the alternative is leaving every validate
		# skippable. Adding a key narrows what a document accepts; nothing else changes.
		base_document.RESERVED_KEYWORDS = base_document.RESERVED_KEYWORDS | {"_action"}
