"""Clear redirects and conditions a CRM public form must not store.

Before ``crm.api.form.save_form`` checked them, a Sales Manager could save a
``javascript:`` success_url, which both public pages navigate to after a
submission, and an ``eval:`` condition outside the grammar crm_form.html parses,
which frappe's own page at /<route> and the builder preview run as code. Either
is script on the site's origin for whoever opens the form, an admin included.
Those values are blanked here; the form keeps everything else and stays
published. Which forms changed is left in the Error Log for the operator.
"""

import frappe


def execute():
	from crm.api.form import (
		ALLOWED_DOCTYPES,
		CONDITION_KEYS,
		FORM_MODULE,
		_is_safe_condition,
		_is_safe_redirect_url,
	)

	forms = frappe.get_all(
		"Web Form",
		filters={"module": FORM_MODULE, "doc_type": ("in", ALLOWED_DOCTYPES)},
		pluck="name",
	)
	changed = []
	for name in forms:
		doc = frappe.get_doc("Web Form", name)
		cleared = []
		if not _is_safe_redirect_url(doc.success_url):
			doc.success_url = ""
			cleared.append("redirect URL")
		for row in doc.web_form_fields:
			for key in CONDITION_KEYS:
				if not _is_safe_condition(row.get(key)):
					row.set(key, "")
					cleared.append(f"{row.fieldname} {key}")
		if not cleared:
			continue
		doc.save(ignore_permissions=True)
		changed.append(f"{doc.name} ({doc.route}): {', '.join(cleared)}")

	if changed:
		frappe.log_error(
			title="CRM forms: unsafe redirects and conditions cleared",
			message="A public form may only redirect to an http(s) URL or a site path, and its "
			"conditions may only compare fields.\n" + "\n".join(changed),
		)
