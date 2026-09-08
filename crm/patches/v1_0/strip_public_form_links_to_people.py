"""Remove Link fields to people and records from CRM public forms.

Before the rule in ``crm.api.form.DENIED_LINK_TARGETS`` the builder offered
``organization`` (CRM Organization), ``lead_owner``/``deal_owner`` (User),
``contact`` and ``lead`` as collectible fields. Frappe's guest-whitelisted
``web_form.get_link_options`` lists every record of such a target for any
published, login-free form, so a form carrying one published the customer list
or the reps' emails. The rows are dropped here; the form keeps everything else
and stays published. Which forms changed is left in the Error Log for the
operator.
"""

import frappe


def execute():
	from crm.api.form import ALLOWED_DOCTYPES, DENIED_LINK_TARGETS, FORM_MODULE

	forms = frappe.get_all(
		"Web Form",
		filters={"module": FORM_MODULE, "doc_type": ("in", ALLOWED_DOCTYPES)},
		pluck="name",
	)
	changed = []
	for name in forms:
		doc = frappe.get_doc("Web Form", name)
		dropped = [
			row.fieldname
			for row in doc.web_form_fields
			if row.fieldtype == "Link" and row.options in DENIED_LINK_TARGETS
		]
		if not dropped:
			continue
		doc.web_form_fields = [
			row
			for row in doc.web_form_fields
			if not (row.fieldtype == "Link" and row.options in DENIED_LINK_TARGETS)
		]
		for idx, row in enumerate(doc.web_form_fields, start=1):
			row.idx = idx
		doc.save(ignore_permissions=True)
		changed.append(f"{doc.name} ({doc.route}): {', '.join(dropped)}")

	if changed:
		frappe.log_error(
			title="CRM forms: Link fields to people and records removed",
			message="Public forms must not list users, leads, deals, contacts or organizations.\n"
			+ "\n".join(changed),
		)
