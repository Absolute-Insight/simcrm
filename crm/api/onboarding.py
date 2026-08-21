import frappe


@frappe.whitelist()
def get_first_lead():
	# Same rule as get_first_deal below: the step opens this record, so it
	# must be one the caller may read.
	lead = frappe.get_list(
		"CRM Lead",
		filters={"converted": 0},
		fields=["name"],
		order_by="creation",
		limit=1,
	)
	return lead[0].name if lead else None


@frappe.whitelist()
def get_first_deal():
	# get_list, not get_all: the onboarding step navigates to whatever comes
	# back, and get_all ignores permissions -- a Sales User was handed the
	# oldest deal on the site, which they could not read, and the step died
	# with a 403. Permission-aware, the answer is the first deal *they* can
	# open, or None, and the step falls back to asking them to create one.
	deal = frappe.get_list(
		"CRM Deal",
		fields=["name"],
		order_by="creation",
		limit=1,
	)
	return deal[0].name if deal else None
