import frappe
from pypika import Criterion

from crm.api.session import get_session_role_flags


@frappe.whitelist()
def get_views(doctype: str):
	# The public views are the team's saved filters and columns; an account
	# with no CRM role has no business reading how the pipeline is sliced.
	get_session_role_flags()

	View = frappe.qb.DocType("CRM View Settings")
	query = (
		frappe.qb.from_(View)
		.select("*")
		.where(Criterion.any([View.user == "", View.user == frappe.session.user]))
	)
	if doctype:
		query = query.where(View.dt == doctype)
	views = query.run(as_dict=True)
	return views
