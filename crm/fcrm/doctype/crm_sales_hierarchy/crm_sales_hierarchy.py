# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet, update_nsm


class CRMSalesHierarchy(NestedSet):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		full_name: DF.Data | None
		is_group: DF.Check
		lft: DF.Int
		old_parent: DF.Link | None
		reports_to: DF.Link | None
		rgt: DF.Int
		user: DF.Link | None
	# end: auto-generated types

	nsm_parent_field = "reports_to"

	def on_update(self):
		update_nsm(self)
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")

	def validate(self):
		if self.user:
			# Ensure the same user is not mapped to two different nodes
			existing = frappe.db.get_value(
				"CRM Sales Hierarchy",
				{"user": self.user, "name": ["!=", self.name]},
				"name",
			)
			if existing:
				frappe.throw(
					frappe._("User {0} is already mapped to hierarchy node {1}.").format(self.user, existing)
				)

		# A node with reports_to becomes a child so its parent must be a group
		if self.reports_to and not frappe.db.get_value("CRM Sales Hierarchy", self.reports_to, "is_group"):
			frappe.db.set_value("CRM Sales Hierarchy", self.reports_to, "is_group", 1)

	def on_trash(self):
		# super() is load-bearing, and this override used to skip it. NestedSet's
		# on_trash does two things nothing else does: validate_if_child_exists()
		# refuses to delete a manager who still has reports, and update_nsm()
		# repairs the lft/rgt bounds every subtree query depends on. Without
		# them, offboarding a manager silently orphaned their reports in the
		# tree that defines rep isolation -- so a rep could keep or lose
		# visibility of deals depending on where the bounds landed.
		super().on_trash()
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")


# The roles the Sales Hierarchy pane ranks, most privileged first; the same
# order crm.api.session.get_users resolves a user's role by.
NODE_ROLES = ("System Manager", "Sales Manager", "Sales User")


@frappe.whitelist()
def get_node_users() -> list[dict]:
	"""Whether each user placed in the tree is enabled, and their CRM role.

	The Sales Hierarchy pane classified its rows from crm.api.session.get_users,
	which lists enabled users only. A rep disabled after being placed was not in
	it, so they read as an enabled Sales User and the "disabled" badge could
	never show; and a node whose user held System Manager had no rank, so the
	pane dropped it and showed its direct reports as top-level rows.

	Managers only, like the pane. ``role`` is None for a user who no longer
	holds any CRM role.
	"""
	frappe.only_for(("System Manager", "Sales Manager"))
	users = frappe.get_all("CRM Sales Hierarchy", filters={"user": ["is", "set"]}, pluck="user")
	if not users:
		return []

	enabled = dict(
		frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "enabled"], as_list=True)
	)
	held: dict[str, set[str]] = {}
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "parent": ["in", users], "role": ["in", NODE_ROLES]},
		fields=["parent", "role"],
	):
		held.setdefault(row.parent, set()).add(row.role)

	def role_of(user: str) -> str | None:
		# Administrator's Has Role rows are not guaranteed to list System Manager
		if user == "Administrator":
			return "System Manager"
		return next((role for role in NODE_ROLES if role in held.get(user, ())), None)

	return [{"user": user, "enabled": int(enabled.get(user) or 0), "role": role_of(user)} for user in users]


def on_doctype_update():
	frappe.db.add_index("CRM Sales Hierarchy", ["lft", "rgt"])
	frappe.db.add_index("CRM Sales Hierarchy", ["user"])
