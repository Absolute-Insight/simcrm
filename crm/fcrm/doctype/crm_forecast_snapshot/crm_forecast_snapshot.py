# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMForecastSnapshot(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_at_snapshot: DF.Float
		forecasted: DF.Float
		month: DF.Data
		name: DF.Int | None
		snapshot_date: DF.Date
	# end: auto-generated types
