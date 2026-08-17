# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Put the signal thresholds back on sites the settings page zeroed.

The Assistant settings page read its fields with ``frappe.client.get_value``,
which returns ``{}`` for a Single nobody has saved. Every field came back
undefined, and saving the page wrote each one as 0 -- so an admin who opened the
page to point the CRM at a model endpoint also, invisibly, switched off the whole
deterministic suggestion engine and collapsed its four thresholds.

The fingerprint is unambiguous: all four thresholds at 0 at once. Nothing an
admin can mean by that -- ``SignalConfig`` already clamps a 0 to one day, so the
value carries no intent -- and no filled-in form produces it, since each of the
four inputs would have to be typed to zero by hand. Where the fingerprint
matches, the defaults go back, ``signals_enabled`` included: the same broken
save is what turned it off.

An admin who genuinely wants suggestions off can switch them off again. This
time it will stick.
"""

import frappe

from crm.agent.config import SIGNAL_DEFAULTS

THRESHOLDS = ("idle_deal_days", "suggestion_ttl_days", "dismiss_cooldown_days", "close_horizon_days")


def execute():
	stored = frappe.db.get_singles_dict("CRM Agent Settings")
	if not stored:
		# Never saved, so never corrupted -- the job is already reading the defaults.
		return

	def is_zero(field):
		value = stored.get(field)
		return value is not None and str(value).strip() in ("0", "0.0")

	if not all(is_zero(field) for field in THRESHOLDS):
		return

	for field, default in SIGNAL_DEFAULTS.items():
		frappe.db.set_single_value("CRM Agent Settings", field, default)

	frappe.logger("crm.agent").warning(
		"CRM Agent Settings: all four signal thresholds were 0, which only the settings"
		" page's undefined-field write produces. Restored the defaults and re-enabled"
		" signal generation."
	)
