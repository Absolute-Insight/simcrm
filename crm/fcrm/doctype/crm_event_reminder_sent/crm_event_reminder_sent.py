# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The event-reminder sent ledger: one row per reminder that has gone out.

The sweep (crm.api.event) claims a reminder by inserting its row before sending it;
the row's name is the reminder's key, so a second sweep's insert of the same one
fails, however close together they run. Written on a connection of its own
(crm.utils.autonomous) so the claim stands even if the sweep's job is rolled back
after the mail went -- and not in the cache redis, where it used to be, which a
flush, an eviction or a restart emptied and every participant was mailed again.
"""

from datetime import timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.utils.autonomous import autonomous_db, is_duplicate

DOCTYPE = "CRM Event Reminder Sent"
TABLE = f"`tab{DOCTYPE}`"

# Long past the catch-up window (an hour), after which a reminder cannot fire again.
KEEP_DAYS = 3


class CRMEventReminderSent(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		event: DF.Data | None
		notification_type: DF.Data | None
		reminder_key: DF.Data
		sent_at: DF.Datetime | None
		trigger_at: DF.Datetime | None
	# end: auto-generated types

	pass


def claim(key: str, event: str, notification_type: str, trigger_at) -> bool:
	"""Record that the reminder ``key`` is going out; False when it already went."""
	now = now_datetime()
	with autonomous_db() as db:
		try:
			db.sql(
				f"""insert into {TABLE}
					(name, reminder_key, event, notification_type, trigger_at, sent_at,
					creation, modified, owner, modified_by, docstatus, idx)
				values (%s, %s, %s, %s, %s, %s, %s, %s, 'Administrator', 'Administrator', 0, 0)""",
				(key, key, event, notification_type, trigger_at, now, now, now),
			)
		except Exception as e:
			if is_duplicate(db, e):
				return False
			raise
	return True


def purge_old() -> None:
	"""Daily: drop rows for reminders that can no longer fire."""
	cutoff = now_datetime() - timedelta(days=KEEP_DAYS)
	with autonomous_db() as db:
		db.sql(f"delete from {TABLE} where sent_at < %s", (cutoff,))
