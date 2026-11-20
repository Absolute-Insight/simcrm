# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json
import os

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.api import form as F
from crm.tests.test_form_api import make_form
from crm.utils.form_conditions import review_submission, truthy

with open(os.path.join(os.path.dirname(__file__), "form_condition_cases.json")) as f:
	CASES = json.load(f)["cases"]


class TestConditionEvaluation(UnitTestCase):
	def test_agrees_with_the_public_page(self):
		"""The same list runs against truthy() in crm_form.html
		(webFormConditionalEval.test.js): the server must enforce exactly what the
		page shows, JavaScript's coercions included."""
		for expr, doc, fallback, expected in CASES:
			with self.subTest(expr=expr, doc=doc, fallback=fallback):
				self.assertIs(truthy(expr, doc, fallback), expected)

	def test_review_follows_the_page(self):
		fields = [
			{"fieldname": "kind", "fieldtype": "Select"},
			{"fieldname": "company", "fieldtype": "Data", "depends_on": "eval:doc.kind == 'Company'"},
			{"fieldname": "vat", "fieldtype": "Data", "mandatory_depends_on": "eval:doc.kind == 'Company'"},
			{"fieldname": "locked", "fieldtype": "Data", "reqd": 1, "read_only_depends_on": "eval:true"},
			{"fieldname": "agree", "fieldtype": "Check", "reqd": 1},
			{"fieldname": "sb", "fieldtype": "Section Break", "reqd": 1},
		]
		hidden, missing = review_submission(fields, {"kind": "Person", "company": "Acme", "agree": 1})
		self.assertEqual(hidden, ["company"])
		self.assertEqual(missing, [])

		_, missing = review_submission(fields, {"kind": "Company", "agree": 0})
		self.assertEqual([f["fieldname"] for f in missing], ["vat", "agree"])

		_, missing = review_submission(fields, {"kind": "Company", "vat": "X1", "agree": "0"})
		self.assertEqual([f["fieldname"] for f in missing], ["agree"])

	def test_a_required_field_hidden_by_its_condition_is_not_required(self):
		fields = [
			{"fieldname": "a", "fieldtype": "Data"},
			{"fieldname": "b", "fieldtype": "Data", "reqd": 1, "depends_on": "a"},
		]
		self.assertEqual(review_submission(fields, {"a": ""}), (["b"], []))
		_, missing = review_submission(fields, {"a": "x"})
		self.assertEqual([f["fieldname"] for f in missing], ["b"])


CONDITIONAL_FIELDS = [
	{"fieldname": "first_name", "fieldtype": "Data", "reqd": 1},
	{"fieldname": "organization", "fieldtype": "Data"},
	{"fieldname": "website", "fieldtype": "Data", "depends_on": "eval:doc.organization"},
	{
		"fieldname": "last_name",
		"fieldtype": "Data",
		"mandatory_depends_on": 'eval:doc.organization == "Acme"',
	},
]


class TestFormConditionsOnSubmission(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_web_form = False
		frappe.form_dict.pop("web_form", None)
		frappe.db.rollback()

	def submit(self, form, doctype="CRM Lead", **values):
		"""What accept() does: flag the request, name the form, insert the values."""
		frappe.flags.in_web_form = True
		frappe.form_dict["web_form"] = form
		return frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)

	def test_a_required_if_answer_cannot_be_skipped(self):
		form = make_form("cond-required-if", fields=CONDITIONAL_FIELDS)
		with self.assertRaises(frappe.MandatoryError):
			self.submit(form, first_name="Ada", organization="Acme", email="cond-a@test.invalid")

	def test_a_complete_submission_is_accepted(self):
		form = make_form("cond-complete", fields=CONDITIONAL_FIELDS)
		lead = self.submit(
			form, first_name="Ada", organization="Acme", last_name="L", email="cond-b@test.invalid"
		)
		self.assertEqual(lead.last_name, "L")
		# the condition does not hold, so the field is optional
		self.submit(form, first_name="Bo", organization="Other", email="cond-c@test.invalid")

	def test_an_answer_to_a_hidden_field_is_dropped(self):
		form = make_form("cond-hidden", fields=CONDITIONAL_FIELDS)
		lead = self.submit(form, first_name="Ada", website="https://x.test", email="cond-d@test.invalid")
		self.assertFalse(lead.website)
		shown = self.submit(
			form, first_name="Bo", organization="Other", website="https://y.test", email="cond-e@test.invalid"
		)
		self.assertEqual(shown.website, "https://y.test")

	def test_only_the_named_forms_rules_for_this_doctype_apply(self):
		"""`web_form` is client-controlled: a Deal form's rules don't bind a Lead."""
		deal_form = make_form(
			"cond-deal",
			document_type="CRM Deal",
			fields=[{"fieldname": "website", "fieldtype": "Data", "reqd": 1}],
		)
		self.submit(deal_form, first_name="Ada", email="cond-f@test.invalid")

	def test_nothing_changes_outside_a_web_form_submission(self):
		make_form("cond-desk", fields=CONDITIONAL_FIELDS)
		frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Ada", "organization": "Acme", "email": "cond-g@test.invalid"}
		).insert(ignore_permissions=True)

	def test_the_draft_preview_applies_the_same_rules(self):
		form = make_form("cond-preview", fields=CONDITIONAL_FIELDS)
		with self.assertRaises(frappe.MandatoryError):
			F.test_submit_form(form, {"first_name": "Ada", "organization": "Acme"})
		self.assertEqual(
			F.test_submit_form(form, {"first_name": "Ada", "organization": "Acme", "last_name": "L"}),
			{"test": True},
		)
