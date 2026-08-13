# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The agent role must exist, be read-only, and survive being created twice."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.install import AGENT_ROLE, READABLE_DOCTYPES, ensure_agent_role


class AgentRoleTest(IntegrationTestCase):
	def test_role_is_created(self):
		ensure_agent_role()
		self.assertTrue(frappe.db.exists("Role", AGENT_ROLE))

	def test_running_twice_is_harmless(self):
		ensure_agent_role()
		ensure_agent_role()
		self.assertEqual(frappe.db.count("Role", {"name": AGENT_ROLE}), 1)

	def test_role_grants_read_only(self):
		ensure_agent_role()
		for doctype in READABLE_DOCTYPES:
			if not frappe.db.exists("DocType", doctype):
				continue
			perm = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": AGENT_ROLE},
				["read", "write", "create", "delete"],
				as_dict=True,
			)
			self.assertIsNotNone(perm, f"no permission row for {doctype}")
			self.assertEqual(int(perm.read), 1)
			self.assertEqual(int(perm.write), 0)
			self.assertEqual(int(perm.create), 0)
			self.assertEqual(int(perm.delete), 0)
