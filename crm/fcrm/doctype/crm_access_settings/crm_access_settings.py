# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

CONFIGURABLE_ROLES = ("Sales Manager", "Sales User")

#: The doctype's own Select options for ``manager_outside_hierarchy``. Kept here
#: because ``crm.api.access.set_data_access`` writes this field through
#: ``frappe.db.set_single_value``, which bypasses both this file's ``validate()``
#: and frappe's own Select validation -- so this tuple is the *only* enforcement
#: on that path.
MANAGER_SCOPES = ("All records", "Own records only")


class CRMAccessSettings(Document):
	def validate(self):
		self.reject_unconfigurable_roles()
		self.drop_duplicate_rows()

	def reject_unconfigurable_roles(self):
		"""There is no System Manager column, by design.

		Nothing is hideable from an administrator, which is what stops an admin
		configuring themselves out of the one pane that would undo it. Enforced
		on the doctype and not only in the endpoint, because the desk form is a
		second door.
		"""
		for row in self.hidden_surfaces:
			if row.role not in CONFIGURABLE_ROLES:
				frappe.throw(
					_("{0} is not a configurable role. Nothing can be hidden from an administrator.").format(
						row.role
					)
				)

	def drop_duplicate_rows(self):
		"""One row per (role, surface). Duplicates are harmless to read but they
		make the desk table lie about how many surfaces are hidden."""
		seen = set()
		kept = []
		for row in self.hidden_surfaces:
			key = (row.role, row.surface)
			if key in seen:
				continue
			seen.add(key)
			kept.append(row)
		self.hidden_surfaces = kept
