import frappe


def execute():
	"""Refile Notes views under the route the SPA has.

	get_route_name turned "FCRM Note" into "FCRM Notes", so a Notes view made
	without a route_name from the client -- Set As Default on an untouched view
	-- was filed under a route that does not exist, and a manager whose only
	default it was landed on a blank Home every login.
	"""
	frappe.db.set_value(
		"CRM View Settings",
		{"dt": "FCRM Note", "route_name": "FCRM Notes"},
		"route_name",
		"Notes",
		update_modified=False,
	)
