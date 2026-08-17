# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from crm.lead_syncing import throw_if_disabled
from crm.lead_syncing.doctype.lead_sync_source.facebook import (
	FacebookSyncSource,
	fetch_and_store_pages_from_facebook,
)


class LeadSyncSource(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_token: DF.Password
		background_sync_frequency: DF.Literal[
			"Every 5 Minutes", "Every 10 Minutes", "Every 15 Minutes", "Hourly", "Daily", "Monthly"
		]
		enabled: DF.Check
		facebook_lead_form: DF.Link | None
		facebook_page: DF.Link | None
		last_synced_at: DF.Datetime | None
		type: DF.Literal["Facebook"]
	# end: auto-generated types

	def validate(self):
		self.validate_syncing_available()
		self.validate_same_fb_form_active()

	def validate_syncing_available(self):
		# Only enabling is blocked, not every save: a source that is already
		# enabled on an upgraded site has to stay editable, or the admin cannot
		# untick the box to turn it off.
		if self.enabled:
			throw_if_disabled()

	def validate_same_fb_form_active(self):
		if not self.enabled:
			return

		if not self.facebook_lead_form:
			return

		already_active = frappe.db.exists(
			"Lead Sync Source",
			{"enabled": 1, "facebook_lead_form": self.facebook_lead_form, "name": ["!=", self.name]},
		)

		if already_active:
			frappe.throw(frappe._("A lead sync source is already enabled for this Facebook Lead Form!"))

	def before_insert(self):
		if self.type == "Facebook" and self.access_token:
			fetch_and_store_pages_from_facebook(self.access_token)
		# rest of the source types can be added here

	@frappe.whitelist()
	def sync_leads(self):
		throw_if_disabled()

		if frappe.conf.developer_mode:
			self._sync_leads()
			return

		# after_commit: the worker re-reads this source from the database, so
		# queueing before the request commits lets it start against the old row
		# -- or against no row at all, if the request goes on to roll back.
		frappe.enqueue_doc(self.doctype, self.name, "_sync_leads", queue="long", enqueue_after_commit=True)

	def _sync_leads(self):
		# Last line of defence: this is what the background jobs and the
		# enqueued "Sync Now" both land on, including a job that was queued
		# before the feature was switched off.
		throw_if_disabled()

		if self.type == "Facebook" and self.access_token:
			if not self.facebook_lead_form:
				frappe.throw(frappe._("Please select a lead gen form before syncing!"))

			FacebookSyncSource(self.get_password("access_token"), self.facebook_lead_form).sync()
