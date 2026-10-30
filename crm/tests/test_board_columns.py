# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a kanban column holds, and what building the board costs."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import MAX_KANBAN_COLUMNS, get_data


def make_lead(first_name: str, **fields) -> str:
	return (
		frappe.get_doc({"doctype": "CRM Lead", "first_name": first_name, "last_name": "Board", **fields})
		.insert(ignore_permissions=True)
		.name
	)


def board(names: list[str], column_field: str) -> dict:
	return get_data(
		doctype="CRM Lead",
		filters={"name": ["in", names]},
		order_by="modified desc",
		column_field=column_field,
		title_field="name",
		kanban_fields=json.dumps(["name"]),
		view={"view_type": "kanban"},
	)


def columns_of(result: dict) -> dict[str, dict]:
	return {
		column["column"]["name"]: {
			"names": sorted(row["name"] for row in column["data"]),
			"all_count": column["column"].get("all_count"),
		}
		for column in result["data"]
	}


class BlankSelectColumnTest(IntegrationTestCase):
	"""A Select field whose options start with a blank gives the board a "" column.

	That column was queried with no column filter at all -- an empty name read as
	"no filter" -- so it listed every record on the board, and every card showed
	twice.
	"""

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_blank_column_holds_only_the_records_with_no_value(self):
		buyer = make_lead("Buyer", contact_type="Buyer")
		engineer = make_lead("Engineer", contact_type="Engineer")
		unset = make_lead("Unset")

		columns = columns_of(board([buyer, engineer, unset], "contact_type"))

		self.assertEqual(columns[""], {"names": [unset], "all_count": 1})
		self.assertEqual(columns["Buyer"], {"names": [buyer], "all_count": 1})
		self.assertEqual(columns["Engineer"], {"names": [engineer], "all_count": 1})
		self.assertEqual(columns["Other"], {"names": [], "all_count": 0})


class LinkColumnFanOutTest(IntegrationTestCase):
	"""Every row of a Link column field's target became a column, and every column
	a page query and a COUNT of its own. A deal board grouped by organization ran
	two queries per organization on the site, and timed out on a real one."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.industries = []
		for index in range(MAX_KANBAN_COLUMNS + 10):
			name = f"Board Industry {index:03d}"
			if not frappe.db.exists("CRM Industry", name):
				frappe.get_doc({"doctype": "CRM Industry", "industry": name}).insert(ignore_permissions=True)
			self.industries.append(name)

	def tearDown(self):
		frappe.db.rollback()

	def test_a_board_over_a_large_target_draws_the_values_its_records_use(self):
		busy, quiet = self.industries[-1], self.industries[0]
		leads = [
			make_lead("Busy One", industry=busy),
			make_lead("Busy Two", industry=busy),
			make_lead("Quiet", industry=quiet),
		]

		real_get_list = frappe.get_list
		with patch.object(frappe, "get_list", side_effect=real_get_list) as get_list:
			result = board(leads, "industry")

		columns = columns_of(result)
		self.assertLessEqual(len(columns), MAX_KANBAN_COLUMNS)
		self.assertEqual(columns[busy], {"names": sorted(leads[:2]), "all_count": 2})
		self.assertEqual(columns[quiet], {"names": [leads[2]], "all_count": 1})
		# busiest first
		self.assertEqual([c["column"]["name"] for c in result["data"]][:2], [busy, quiet])
		# reads of the board's own records stay a handful, not a page query and a
		# COUNT for every row of CRM Industry
		lead_reads = [c for c in get_list.call_args_list if c.args and c.args[0] == "CRM Lead"]
		self.assertLess(len(lead_reads), 15)

	def test_a_small_target_still_draws_every_row(self):
		lead = make_lead("Status Board")

		columns = columns_of(board([lead], "status"))

		statuses = frappe.get_all("CRM Lead Status", pluck="name")
		self.assertEqual(sorted(columns), sorted(statuses))
