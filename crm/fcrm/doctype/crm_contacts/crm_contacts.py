# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMContacts(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		contact: DF.Link | None
		email: DF.Data | None
		full_name: DF.Data | None
		gender: DF.Link | None
		is_primary: DF.Check
		mobile_no: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		phone: DF.Data | None
	# end: auto-generated types

	def validate(self):
		"""A deal's contact is saved with its deal, never on its own.

		frappe runs this only when the row itself is saved -- a deal's save does not
		call its rows' controllers -- so a row saved directly skipped the check in
		CRMDeal.validate, and the fetched name, email and mobile came back in the
		response. Attaching a contact the rep cannot see was a way to read it.
		"""
		if self.flags.ignore_permissions or frappe.session.user == "Administrator":
			return
		frappe.throw(_("A deal's contact is saved with its deal, not on its own."), frappe.PermissionError)
