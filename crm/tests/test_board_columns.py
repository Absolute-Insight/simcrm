# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a kanban column holds."""

from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import get_data


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
