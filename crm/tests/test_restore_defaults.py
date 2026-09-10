# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Restore Defaults must restore fixtures, and nothing else.

The button on FCRM Settings used to call ``after_install`` wholesale, so a
click meant to put one missing layout back also re-read the container's
``VECTORA_AGENT_*`` variables over an endpoint the admin had repointed, reset
who managers can see, and committed inside the request. ``crm.install`` now
splits those apart: ``restore_defaults`` holds the repeatable fixtures,
``after_install`` adds the install-only steps around them.

Every test here mocks ``commit`` -- both because the handler must not issue one
and so a regression cannot commit half a fixture set into the shared test site.
"""

from __future__ import annotations

import inspect
import json
import os
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm import install

LEAD_QUICK_ENTRY = "CRM Lead-Quick Entry"
ADMIN_SECTION = "an_admin_put_this_here"


class RestoreDefaultsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def restore(self, force: bool = False):
		"""Click the button, and hand back the mock that stood in for commit."""
		with patch.object(frappe.local.db, "commit") as commit:
			frappe.get_single("FCRM Settings").restore_defaults(force=force)
		return commit

	def customise_the_lead_quick_entry_layout(self) -> None:
		if not frappe.db.exists("CRM Fields Layout", LEAD_QUICK_ENTRY):
			self.skipTest(f"{LEAD_QUICK_ENTRY} is not installed on this site")
		doc = frappe.get_doc("CRM Fields Layout", LEAD_QUICK_ENTRY)
		layout = json.loads(doc.layout or "[]")
		layout.append({"name": ADMIN_SECTION, "columns": [{"name": "column_admin", "fields": ["job_title"]}]})
		doc.layout = json.dumps(layout)
		doc.save(ignore_permissions=True)

	def lead_quick_entry_layout(self) -> str:
		return frappe.db.get_value("CRM Fields Layout", LEAD_QUICK_ENTRY, "layout") or ""

	def test_restoring_defaults_does_not_commit_inside_the_request(self):
		"""The request commits on success and rolls back on failure. A commit
		half-way through means a fixture set that raised is half applied."""
		self.restore().assert_not_called()

	def test_the_agent_endpoint_an_admin_chose_survives_a_restore(self):
		"""``apply_endpoint_defaults`` seeds the endpoint from the container's
		environment at install time. Re-running it here silently repointed a
		site at whatever the compose file said, with nothing on screen to say
		the model host had moved back."""
		chosen = "https://models.admin-chose-this.invalid"
		previous = frappe.db.get_single_value("CRM Agent Settings", "base_url")
		self.addCleanup(frappe.db.set_single_value, "CRM Agent Settings", "base_url", previous)
		frappe.db.set_single_value("CRM Agent Settings", "base_url", chosen)

		with patch.dict(os.environ, {"VECTORA_AGENT_BASE_URL": "http://vectora-agent:8080"}):
			self.restore()

		self.assertEqual(frappe.db.get_single_value("CRM Agent Settings", "base_url"), chosen)

	def test_access_scoping_survives_a_restore(self):
		"""Narrowing this silently would just stop managers seeing most of the
		pipeline, with no error to explain it."""
		for single, field, value in (
			("FCRM Settings", "enable_sales_hierarchy", 0),
			("CRM Access Settings", "manager_outside_hierarchy", "All records"),
		):
			previous = frappe.db.get_single_value(single, field)
			self.addCleanup(frappe.db.set_single_value, single, field, previous)
			frappe.db.set_single_value(single, field, value)

		self.restore()

		self.assertEqual(frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy"), 0)
		self.assertEqual(
			frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy"),
			"All records",
		)

	def test_restore_adds_what_is_missing_and_keeps_what_is_there(self):
		"""What the dialog's Restore button promises."""
		self.customise_the_lead_quick_entry_layout()
		self.restore(force=False)
		self.assertIn(ADMIN_SECTION, self.lead_quick_entry_layout())

	def test_delete_and_restore_replaces_the_standard_layouts(self):
		"""And what its Delete & Restore button promises -- the confirmation
		copy now names the layouts it replaces, so this is the destructive path
		an admin explicitly asked for rather than a surprise."""
		self.customise_the_lead_quick_entry_layout()
		self.restore(force=True)
		self.assertNotIn(ADMIN_SECTION, self.lead_quick_entry_layout())

	def test_the_install_only_steps_stay_in_after_install(self):
		"""The tests above call the button's path, so they would stay green if
		the split dropped these on the floor -- shipping fresh installs with no
		endpoint and the wide-open access defaults. Same idiom as
		``test_access_settings``'s ``test_after_install_calls_ensure_access_defaults``."""
		after_install = inspect.getsource(install.after_install)
		repeatable = inspect.getsource(install.restore_defaults)

		for step in ("apply_endpoint_defaults()", "ensure_access_defaults()"):
			self.assertIn(step, after_install)
			self.assertNotIn(step, repeatable)

		self.assertIn("restore_defaults(force)", after_install)
		# The fixtures themselves have to stay reachable from a fresh install.
		self.assertIn("add_default_fields_layout(force)", repeatable)
