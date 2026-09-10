# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The columns every scoped query filters on have to be indexed.

Frappe does not index a Link field on its own, so an index only exists if the
doctype JSON asks for one (``search_index``) or a doctype's
``on_doctype_update`` adds it. These are the ones the hierarchy filter, the
kanban, the snapshot job and every Won aggregate range-scan, and they were all
unindexed: at MBP scale each scoped list page was a full table scan per rep per
request.

This reads the shipped JSON rather than ``frappe.get_meta`` or
``frappe.db.has_index`` deliberately. Both of those answer a question about the
*site the test happens to run on* -- whether someone has migrated it with this
branch checked out -- rather than about what the app ships, so on a shared bench
they go red for reasons that have nothing to do with the code. What migrate then
does with the flag is Frappe's job and is covered by Frappe's own schema tests.
"""

from __future__ import annotations

import json
import os

from frappe.tests import UnitTestCase

DOCTYPE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fcrm", "doctype")

# fieldname -> why it is hot
INDEXED_FIELDS = {
	"crm_deal": {
		"deal_owner": "every non-admin list, count and kanban query filters on it",
		"closed_date": "every Won aggregate range-scans it",
		"expected_closure_date": "the forecast reads open deals by expected close month",
	},
	"crm_lead": {
		"lead_owner": "the hierarchy filter scopes leads by owner",
	},
}


class HotColumnIndexTest(UnitTestCase):
	def load(self, doctype_dir: str) -> dict:
		path = os.path.join(DOCTYPE_DIR, doctype_dir, f"{doctype_dir}.json")
		with open(path) as f:
			return json.load(f)

	def test_the_scoped_query_columns_declare_an_index(self):
		for doctype_dir, fields in INDEXED_FIELDS.items():
			meta = self.load(doctype_dir)
			by_name = {field["fieldname"]: field for field in meta["fields"]}
			for fieldname, why in fields.items():
				with self.subTest(doctype=meta["name"], fieldname=fieldname):
					self.assertIn(fieldname, by_name)
					self.assertEqual(
						by_name[fieldname].get("search_index"),
						1,
						f"{meta['name']}.{fieldname} needs an index: {why}",
					)
