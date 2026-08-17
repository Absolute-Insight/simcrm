import frappe

# Lead syncing is off unless a site opts in, because the Facebook connector
# loses leads.
#
# FacebookSyncSource.fetch_leads() asks the Graph API for a page of 100000 and
# ignores the paging cursor it answers with (facebook.py carries the "TODO:
# pagination" to prove it). Graph caps a page well below that, so a form with
# more new leads than fit one page hands back a partial batch. sync() then
# calls update_last_synced_at() unconditionally, moving the watermark to now --
# and the next run filters on time_created > watermark, so the leads that never
# arrived in page one are never asked for again. They are not queued, not
# retried, and not written to Failed Lead Sync Log: they are gone, and the sync
# reports success.
#
# A CRM may drop many things quietly. Inbound leads is not one of them, and the
# failure is silent in exactly the case that matters -- a campaign doing well
# enough to overflow a page. So the connector stays off until fetch_leads()
# follows paging.next and the watermark advances only as far as the newest lead
# actually imported.
#
# Set crm_enable_lead_syncing in site config to run it anyway, knowing the above.
CONFIG_KEY = "crm_enable_lead_syncing"


def lead_syncing_enabled() -> bool:
	return bool(frappe.conf.get(CONFIG_KEY))


def disabled_message() -> str:
	# Built per call, not at import: translation is request-scoped.
	return frappe._(
		"Lead syncing is turned off in this deployment. The Facebook connector reads"
		" only the first page of new leads and then marks everything up to now as"
		" synced, so any lead beyond that page is dropped without a trace. Set"
		" {0} in site config to enable it anyway."
	).format(CONFIG_KEY)


def throw_if_disabled() -> None:
	if not lead_syncing_enabled():
		frappe.throw(disabled_message(), title=frappe._("Lead Syncing Disabled"))


@frappe.whitelist()
def is_lead_syncing_enabled() -> bool:
	return lead_syncing_enabled()
