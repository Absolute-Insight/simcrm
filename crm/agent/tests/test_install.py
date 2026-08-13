# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The agent role must exist, survive being created twice, and grant nothing yet.

There are no DocPerm assertions on purpose: ``ensure_agent_role`` deliberately creates
no permission rows, because ``add_permission`` would freeze standard perms on shared
core doctypes (see the module docstring in ``crm/agent/install.py``).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.install import AGENT_ROLE, ensure_agent_role


class AgentRoleTest(IntegrationTestCase):
	def test_role_is_created(self):
		ensure_agent_role()
		self.assertTrue(frappe.db.exists("Role", AGENT_ROLE))

	def test_running_twice_is_harmless(self):
		ensure_agent_role()
		ensure_agent_role()
		self.assertEqual(frappe.db.count("Role", {"name": AGENT_ROLE}), 1)

	def test_no_permissions_are_frozen_for_the_role(self):
		"""A ``Custom DocPerm`` row here means the perm loop is back, and with it the
		irreversible snapshot of standard perms on ``Contact`` and ``Communication``."""
		ensure_agent_role()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"role": AGENT_ROLE}), 0)
