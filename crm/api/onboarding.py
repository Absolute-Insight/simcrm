import frappe


@frappe.whitelist()
def get_first_lead(name: str | None = None):
	# Same rule as get_first_deal below: the step opens this record, so it
	# must be one the caller may read.
	#
	# The sidebar caches the lead it was last handed. That lead may since have
	# been deleted, converted, or moved out of the caller's reach, so the cached
	# name is validated here and the oldest readable lead is the fallback.
	if name and frappe.get_list("CRM Lead", filters={"name": name, "converted": 0}, pluck="name", limit=1):
		return name

	lead = frappe.get_list(
		"CRM Lead",
		filters={"converted": 0},
		pluck="name",
		order_by="creation",
		limit=1,
	)
	return lead[0] if lead else None


@frappe.whitelist()
def get_first_deal(name: str | None = None):
	# get_list, not get_all: the onboarding step navigates to whatever comes
	# back, and get_all ignores permissions -- a Sales User was handed the
	# oldest deal on the site, which they could not read, and the step died
	# with a 403. Permission-aware, the answer is the first deal *they* can
	# open, or None, and the step falls back to asking them to create one.
	if name and frappe.get_list("CRM Deal", filters={"name": name}, pluck="name", limit=1):
		return name

	deal = frappe.get_list(
		"CRM Deal",
		pluck="name",
		order_by="creation",
		limit=1,
	)
	return deal[0] if deal else None
