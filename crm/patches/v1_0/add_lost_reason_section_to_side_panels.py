import json

import frappe

from crm.fcrm.doctype.utils import with_lost_reason_section


def execute():
	"""Put the Lost Reason section in the deal and lead side panels for good.

	It was added to and removed from the one shared layout by whichever record
	last changed status, so a site's layout holds it or not by accident. The
	page now hides it on records that are not Lost.
	"""
	for doctype in ("CRM Deal", "CRM Lead"):
		name = frappe.db.get_value("CRM Fields Layout", {"dt": doctype, "type": "Side Panel"})
		if not name:
			continue
		layout = frappe.db.get_value("CRM Fields Layout", name, "layout")
		sections = json.loads(layout or "[]")
		if not isinstance(sections, list):
			continue
		updated = with_lost_reason_section(sections)
		if updated is not sections:
			frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(updated))
