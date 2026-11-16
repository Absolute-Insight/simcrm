"""Carry the event-reminder claims out of the cache redis into CRM Event Reminder Sent.

Until this release a sent reminder was recorded as ``crm:event_reminder_sent:<key>`` in
redis; from this release the sweep reads only the table. Without this, every reminder
sent in the last catch-up hour before the upgrade would go out a second time after it,
to every participant, customers included.

Idempotent: a reminder already in the table is skipped. With redis empty it does
nothing; unreachable, it raises so migrate runs it again. The keys can still be read
here because hooks.persistent_cache_keys keeps their prefix for this release (migrate
runs frappe.clear_cache() before its patches).
"""

from datetime import datetime

import frappe

from crm.fcrm.doctype.crm_event_reminder_sent.crm_event_reminder_sent import claim
from crm.patches.v1_0.carry_acumatica_inflight_markers_to_ledger import live_keys

PREFIX = "crm:event_reminder_sent:"


def execute():
	cache = frappe.cache()
	site_prefix = frappe.safe_decode(cache.make_key(""))
	carried = 0
	for raw_key in live_keys(cache, PREFIX):
		key = frappe.safe_decode(raw_key)
		if key.startswith(site_prefix):
			key = key[len(site_prefix) :]
		if not key.startswith(PREFIX):
			continue
		reminder_key = key[len(PREFIX) :]
		# <event>:<type>:<trigger time, ISO -- itself full of colons>
		event, notification_type, trigger = [*reminder_key.split(":", 2), "", ""][:3]
		try:
			trigger_at = datetime.fromisoformat(trigger)
		except ValueError:
			trigger_at = None
		if claim(reminder_key, event, notification_type, trigger_at):
			carried += 1
	if carried:
		print(f"Carried {carried} sent event reminder(s) into CRM Event Reminder Sent")
