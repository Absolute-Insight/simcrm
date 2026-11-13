# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One row per entry a device replayed from its outbox.

It exists so a retry is harmless. A phone that sent a visit and lost the
answer in a tunnel sends it again; the receipt is how the server knows it has
already been applied (see ``crm.api.offline.replay``). Nothing reads these
rows for any other purpose, and no role may create or edit one by hand.
"""

from datetime import timedelta

import frappe
from frappe.model.document import Document

# Long past any ordinary retry: a device re-sends within moments of
# reconnecting. Not past every retry -- an entry whose answer was lost stays in
# the outbox of a phone left in a drawer -- so this is also the oldest entry
# ``replay`` will take, and the oldest a device sends on its own
# (OUTBOX_MAX_AGE_DAYS in the frontend's utils/fieldOutbox.js, which a unit
# test holds to this line). Change the number here and nowhere else.
RECEIPT_DAYS = 90


class CRMOfflineReceipt(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Data
		captured_at: DF.Datetime | None
		late: DF.Check
		request_id: DF.Data
		user: DF.Link
	# end: auto-generated types

	pass


def purge_old_receipts() -> None:
	"""Daily: drop receipts no device could still be retrying against."""
	cutoff = frappe.utils.now_datetime() - timedelta(days=RECEIPT_DAYS)
	frappe.db.delete("CRM Offline Receipt", {"creation": ("<", cutoff)})
