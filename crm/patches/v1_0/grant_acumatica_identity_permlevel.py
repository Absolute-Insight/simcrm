"""Level-1 rows for the doctypes whose Acumatica fields moved to permlevel 1.

CRM Deal's acumatica_customer / acumatica_sales_quote and the Acumatica settings'
sync_issues table are permlevel 1 now, with the level-1 rows in the doctype JSON.
Custom DocPerm replaces a doctype's permissions wholesale, so on a site that
customised either doctype those rows never arrive: reps could not read a deal's
customer code and the quote button would hide. Only such a site is touched -- a
Custom DocPerm on a clean one would freeze its permissions against later releases
(same rule as backfill_organization_account_owner).
"""

import frappe

GRANTS = {
	# role -> write at level 1
	"CRM Deal": {"System Manager": 1, "Sales Manager": 1, "Sales User": 0},
	"CRM Acumatica Settings": {"System Manager": 0},
}


def execute():
	for doctype, roles in GRANTS.items():
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
			continue
		for role, write in roles.items():
			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 1}):
				continue
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": role,
					"permlevel": 1,
					"read": 1,
					"write": write,
				}
			).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)
