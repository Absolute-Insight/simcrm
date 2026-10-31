"""Give every customer the rep it belongs to, and show the field on the page.

``account_owner`` is new: without a value every organization is unclaimed, and
unclaimed customers are visible to every rep -- the rule would change nothing.
The owner is the rep with the most deals and planned visits on the customer,
the more recent activity breaking a tie. Only plain reps qualify (see
``can_own_customers``): an account parked on a manager or Administrator would
hide it from every rep, so those stay unclaimed for a manager to assign.
"""

import json

import frappe
from frappe.query_builder.functions import Count, Max

from crm.permissions.customers import can_own_customers

DOCTYPE = "CRM Organization"


def execute():
	grant_on_customised_permissions()
	add_to_side_panel()
	backfill()


def grant_on_customised_permissions():
	"""Custom DocPerm replaces a doctype's permissions wholesale, so on a site that
	customised them the doctype's permlevel 1 rows never arrive: nobody could read
	the field, and no manager could reassign a customer while the rule walled reps
	off. Only such a site is touched; a Custom DocPerm on a clean one would freeze
	its permissions against later releases."""
	if not frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE}):
		return
	for role, write in (("System Manager", 1), ("Sales Manager", 1), ("Sales User", 0)):
		if frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE, "role": role, "permlevel": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 1,
				"read": 1,
				"write": write,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)


def backfill():
	Deal = frappe.qb.DocType("CRM Deal")
	Item = frappe.qb.DocType("CRM Rep Plan Item")
	Plan = frappe.qb.DocType("CRM Rep Plan")
	deals = (
		frappe.qb.from_(Deal)
		.select(
			Deal.organization, Deal.deal_owner.as_("user"), Count("*").as_("n"), Max(Deal.modified).as_("at")
		)
		.where(Deal.organization.isnotnull() & (Deal.organization != "") & Deal.deal_owner.isnotnull())
		.groupby(Deal.organization, Deal.deal_owner)
		.run(as_dict=True)
	)
	visits = (
		frappe.qb.from_(Item)
		.join(Plan)
		.on(Item.parent == Plan.name)
		.select(Item.organization, Plan.user, Count("*").as_("n"), Max(Item.planned_date).as_("at"))
		.where(Item.organization.isnotnull() & (Item.organization != ""))
		.groupby(Item.organization, Plan.user)
		.run(as_dict=True)
	)

	eligible: dict[str, bool] = {}
	tally: dict[str, dict[str, list]] = {}
	for row in deals + visits:
		if row.user not in eligible:
			eligible[row.user] = can_own_customers(row.user)
		if not eligible[row.user]:
			continue
		entry = tally.setdefault(row.organization, {}).setdefault(row.user, [0, ""])
		entry[0] += row.n
		entry[1] = max(entry[1], str(row.at or ""))

	unowned = set(
		frappe.get_all(
			"CRM Organization",
			filters={"account_owner": ["is", "not set"]},
			pluck="name",
			limit=0,
		)
	)
	for organization, by_user in tally.items():
		if organization not in unowned:
			continue
		owner = max(by_user.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0]))[0]
		frappe.db.set_value("CRM Organization", organization, "account_owner", owner, update_modified=False)


def add_to_side_panel():
	"""After territory in the side panel, unless an admin already placed it."""
	name = "CRM Organization-Side Panel"
	if not frappe.db.exists("CRM Fields Layout", name):
		return
	doc = frappe.get_doc("CRM Fields Layout", name)
	try:
		layout = json.loads(doc.layout or "[]")
	except (TypeError, ValueError):
		return
	columns = [column for section in layout for column in section.get("columns", [])]
	if any("account_owner" in (column.get("fields") or []) for column in columns):
		return
	target = next((c for c in columns if "territory" in (c.get("fields") or [])), None)
	target = target or next((c for c in columns if c.get("fields") is not None), None)
	if target is None:
		return
	fields = target["fields"]
	at = fields.index("territory") + 1 if "territory" in fields else len(fields)
	fields.insert(at, "account_owner")
	doc.layout = json.dumps(layout)
	doc.save(ignore_permissions=True)
