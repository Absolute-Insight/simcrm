# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Which Contact an attendee typed onto an event by address is.

See :mod:`crm.api.attendees`. Reps hold no permission on this doctype at all:
the row names a Contact that may be at another rep's customer, and its event is
one the rep owns, so any read of it -- a list, a filter, a report column --
would answer whose customer the address belongs to.
"""

from frappe.model.document import Document


class CRMEventAttendee(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		contact: DF.Link | None
		email: DF.Data
		event: DF.Data
	# end: auto-generated types

	pass
