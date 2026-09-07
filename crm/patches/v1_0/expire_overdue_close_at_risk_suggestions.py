import frappe


def execute():
	"""Retire the close_at_risk suggestions raised for deals whose close date had already passed.

	The detector is forward-looking by design, but it let past-due dates through and
	scored them highest, so a site with an imported pipeline of stale quotes had every
	rep's inbox capped with identical "Urgent" rows. The detector now skips them; this
	clears the ones already written so the cap is free for live signals on the next
	hourly run. Rows a plan item links to are left alone, as purge_old_suggestions does.
	"""
	stale = frappe.db.sql(
		"""
		select s.name
		from `tabCRM Suggestion` s
		join `tabCRM Deal` d on d.name = s.reference_docname
		where s.signal = 'close_at_risk'
		  and s.status = 'Open'
		  and s.reference_doctype = 'CRM Deal'
		  and d.expected_closure_date < curdate()
		  and not exists (
		    select 1 from `tabCRM Rep Plan Item` i where i.suggestion = s.name
		  )
		""",
		pluck=True,
	)
	if stale:
		frappe.db.set_value("CRM Suggestion", {"name": ("in", stale)}, "status", "Expired", update_modified=False)
