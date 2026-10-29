# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One reference PDF the Assistant answers from, row by row.

Rows live in ``CRM Reference Entry`` and are written only by
``crm.api.reference.import_pack``; an administrator can switch a sheet off
here but not edit its figures, which come from the company's own document.
"""

import frappe
from frappe.model.document import Document


class CRMReferenceSheet(Document):
	def on_update(self):
		from crm.api.reference import clear_cache_after_commit

		clear_cache_after_commit()

	def on_trash(self):
		# The rows go with the sheet and are not kept in Deleted Document: a
		# restored sheet has no rows. Re-importing the pack is the recovery.
		from crm.api.reference import clear_cache_after_commit

		frappe.db.delete("CRM Reference Entry", {"sheet": self.name})
		clear_cache_after_commit()
