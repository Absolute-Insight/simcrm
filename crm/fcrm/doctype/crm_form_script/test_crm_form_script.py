# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the doctype behind the Form Script API.

Form Scripts are a public API — CRM admins write records against them — and this
file was the `bench new-doctype` scaffold, `class …(UnitTestCase): pass`, which
discovery counted and which asserted nothing.

Two contracts are worth holding here.

`get_form_script` **changes the shape of its return value with the number of
matching rows**: a bare string for one, a list for several, None for none. Every
caller has to handle all three, so a change that made it always return a list
would be invisible to a test that only ever created one script.

`validate` protects standard scripts from being edited outside developer mode,
while still allowing them to be switched off. Note the guard exempts
`frappe.flags.in_test`, so a test that just calls `save()` passes whether or not
the guard exists — it has to clear that flag first, or it proves nothing.
"""

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_form_script.crm_form_script import get_form_script

SCRIPT_DT = "CRM Lead"


class TestCRMFormScript(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.created = []
		frappe.db.delete("CRM Form Script", {"dt": SCRIPT_DT})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Form Script", {"dt": SCRIPT_DT})
		super().tearDown()

	def make_script(self, body, view="Form", enabled=1, is_standard=0):
		# autoname is "prompt", so the name has to be supplied.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Form Script",
				"__newname": f"{SCRIPT_DT} {view} {len(self.created)} {enabled}",
				"dt": SCRIPT_DT,
				"view": view,
				"enabled": enabled,
				"is_standard": is_standard,
				"script": body,
			}
		).insert(ignore_permissions=True)
		self.created.append(doc.name)
		return doc

	def test_returns_none_when_nothing_matches(self):
		self.assertIsNone(get_form_script(SCRIPT_DT))

	def test_returns_a_bare_string_for_a_single_script(self):
		self.make_script("class Lead { }")
		# Not a list of one. Callers evaluate this directly.
		self.assertEqual(get_form_script(SCRIPT_DT), "class Lead { }")

	def test_returns_a_list_once_there_is_more_than_one(self):
		self.make_script("class A { }")
		self.make_script("class B { }")
		result = get_form_script(SCRIPT_DT)
		self.assertIsInstance(result, list)
		self.assertCountEqual(result, ["class A { }", "class B { }"])

	def test_disabled_scripts_are_not_returned(self):
		self.make_script("class Off { }", enabled=0)
		self.assertIsNone(get_form_script(SCRIPT_DT))

	def test_a_disabled_script_does_not_change_the_shape_of_the_result(self):
		"""The count that picks string-vs-list must be of *enabled* rows."""
		self.make_script("class On { }")
		self.make_script("class Off { }", enabled=0)
		self.assertEqual(get_form_script(SCRIPT_DT), "class On { }")

	def test_view_selects_the_script(self):
		self.make_script("class FormView { }", view="Form")
		self.make_script("class ListView { }", view="List")
		self.assertEqual(get_form_script(SCRIPT_DT, view="Form"), "class FormView { }")
		self.assertEqual(get_form_script(SCRIPT_DT, view="List"), "class ListView { }")

	def test_doctype_selects_the_script(self):
		"""Asserted as absence, not as None: the app ships its own Deal scripts.

		An `assertIsNone` here would have been testing the fixtures, and would
		start failing the day someone adds another standard script.
		"""
		self.make_script("class Lead { }")
		result = get_form_script("CRM Deal")
		returned = result if isinstance(result, list) else [result] if result else []
		self.assertNotIn("class Lead { }", returned)


class TestStandardFormScriptGuard(IntegrationTestCase):
	"""The guard exempts `frappe.flags.in_test`, which every test runs under.

	So each test here clears the flag for the duration of the save. Without that
	the assertions pass against a build with the guard deleted.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Form Script", {"dt": SCRIPT_DT})
		self.doc = frappe.get_doc(
			{
				"doctype": "CRM Form Script",
				"__newname": "Standard Lead Form Script",
				"dt": SCRIPT_DT,
				"view": "Form",
				"enabled": 1,
				"is_standard": 1,
				"script": "class Standard { }",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = True
		frappe.db.delete("CRM Form Script", {"dt": SCRIPT_DT})
		super().tearDown()

	def save_as_user(self, doc):
		"""Save with the in-test exemption lifted, and developer mode off."""
		in_test = frappe.flags.in_test
		developer_mode = frappe.conf.developer_mode
		frappe.flags.in_test = False
		frappe.conf.developer_mode = 0
		try:
			doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_test = in_test
			frappe.conf.developer_mode = developer_mode

	def test_editing_a_standard_script_is_refused(self):
		self.doc.script = "class Tampered { }"
		with self.assertRaises(frappe.ValidationError):
			self.save_as_user(self.doc)
		self.assertEqual(
			frappe.db.get_value("CRM Form Script", self.doc.name, "script"),
			"class Standard { }",
		)

	def test_a_standard_script_can_still_be_switched_off(self):
		"""Disabling is the one change an admin may make without developer mode."""
		self.doc.enabled = 0
		self.save_as_user(self.doc)
		self.assertEqual(frappe.db.get_value("CRM Form Script", self.doc.name, "enabled"), 0)

	def test_switching_off_does_not_carry_an_edit_along_with_it(self):
		"""`enabled` changed *and* the body changed reloads the body from the db.

		This is the branch that makes the guard hard to get right: it keeps the
		new `enabled` and throws the tampered script away, rather than throwing.
		"""
		self.doc.enabled = 0
		self.doc.script = "class SmuggledIn { }"
		self.save_as_user(self.doc)
		row = frappe.db.get_value("CRM Form Script", self.doc.name, ["enabled", "script"], as_dict=True)
		self.assertEqual(row.enabled, 0)
		self.assertEqual(row.script, "class Standard { }")

	def test_a_non_standard_script_is_freely_editable(self):
		"""The control: without is_standard the same save must go through."""
		other = frappe.get_doc(
			{
				"doctype": "CRM Form Script",
				"__newname": "Mine Lead List Script",
				"dt": SCRIPT_DT,
				"view": "List",
				"enabled": 1,
				"is_standard": 0,
				"script": "class Mine { }",
			}
		).insert(ignore_permissions=True)
		other.script = "class MineEdited { }"
		self.save_as_user(other)
		self.assertEqual(frappe.db.get_value("CRM Form Script", other.name, "script"), "class MineEdited { }")
