import frappe

# Lead syncing is off unless a site opts in.
#
# The reason it was switched off is fixed. fetch_leads() used to ask Graph for a
# page of 100000 and ignore the paging cursor it answered with, while sync()
# moved the watermark to now() regardless -- so a form with more new leads than
# fit one page handed back a partial batch and the rest were marked synced
# without ever being asked for. They were not queued, not retried and not
# written to Failed Lead Sync Log: they were gone, and the sync reported
# success. fetch_leads() now follows paging.next to the end and the watermark
# advances only as far as a lead the run actually handled.
#
# It stays off anyway, for a different and smaller reason: none of that has been
# exercised against live Facebook. The pagination, the cursor host check and the
# watermark are covered by tests against a stubbed Graph API, which is not the
# same as a real form with a real campaign behind it. Turning it on is a
# deliberate act for whoever has an account to point at it.
#
# Set crm_enable_lead_syncing in site config to run it.
CONFIG_KEY = "crm_enable_lead_syncing"


def lead_syncing_enabled() -> bool:
	return bool(frappe.conf.get(CONFIG_KEY))


def disabled_message() -> str:
	# Built per call, not at import: translation is request-scoped.
	return frappe._(
		"Lead syncing is turned off in this deployment. The Facebook connector has not"
		" been run against a live account -- its paging and resume behaviour are covered"
		" by tests against a stubbed Graph API only. Set {0} in site config to enable it."
	).format(CONFIG_KEY)


def throw_if_disabled() -> None:
	if not lead_syncing_enabled():
		frappe.throw(disabled_message(), title=frappe._("Lead Syncing Disabled"))


@frappe.whitelist()
def is_lead_syncing_enabled() -> bool:
	return lead_syncing_enabled()
