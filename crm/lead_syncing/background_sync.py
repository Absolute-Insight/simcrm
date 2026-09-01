import frappe

from crm.lead_syncing import lead_syncing_enabled


def sync_leads_from_all_enabled_sources(frequency: str | None = None) -> None:
	# The scheduler hooks stay registered so that flipping the site config is
	# the whole of re-enabling, rather than a config change that quietly only
	# restores the manual "Sync Now" button. See crm/lead_syncing/__init__.py
	# for why this is off.
	if not lead_syncing_enabled():
		return

	enabled_sources = frappe.get_all(
		"Lead Sync Source", filters={"enabled": 1, "background_sync_frequency": frequency}, pluck="name"
	)
	for source in enabled_sources:
		lead_sync_source = frappe.get_cached_doc("Lead Sync Source", source)
		try:
			lead_sync_source._sync_leads()
		except Exception as _:
			# One source's half-written leads must not ride along with -- or
			# abort -- the next source's transaction.
			frappe.db.rollback()
			frappe.log_error(f"Error syncing leads for source {source}")


def sync_leads_from_sources_5_minutes() -> None:
	sync_leads_from_all_enabled_sources("Every 5 Minutes")


def sync_leads_from_sources_10_minutes() -> None:
	sync_leads_from_all_enabled_sources("Every 10 Minutes")


def sync_leads_from_sources_15_minutes() -> None:
	sync_leads_from_all_enabled_sources("Every 15 Minutes")


def sync_leads_from_sources_hourly() -> None:
	sync_leads_from_all_enabled_sources("Hourly")


def sync_leads_from_sources_daily() -> None:
	sync_leads_from_all_enabled_sources("Daily")


def sync_leads_from_sources_monthly() -> None:
	sync_leads_from_all_enabled_sources("Monthly")
