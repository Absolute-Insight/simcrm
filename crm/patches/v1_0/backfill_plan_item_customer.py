import frappe


def execute():
	"""Give existing plan items the customer their visit was at.

	Plan items had no customer field before; a visit logged from the planner or
	imported from the old rep app named its customer only on the calendar event
	that fulfils it (an Event Participants row). Copying it across makes those
	items show and count against the customer like everything planned from now
	on. Only empty customers are filled, and only from the item's own event, so
	re-running changes nothing.
	"""
	frappe.db.sql(
		"""
		update `tabCRM Rep Plan Item` item
		join (
			select parent, min(reference_docname) as organization
			from `tabEvent Participants`
			where parenttype = 'Event' and reference_doctype = 'CRM Organization'
			group by parent
		) customer on customer.parent = item.fulfilled_by
		set item.organization = customer.organization
		where item.fulfilled_by_doctype = 'Event'
			and (item.organization is null or item.organization = '')
		"""
	)
