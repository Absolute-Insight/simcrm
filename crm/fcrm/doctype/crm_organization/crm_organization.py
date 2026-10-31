# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from crm.api.exchange_rate import get_exchange_rate


class CRMOrganization(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account_owner: DF.Link | None
		address: DF.Link | None
		annual_revenue: DF.Currency
		currency: DF.Link | None
		exchange_rate: DF.Float
		industry: DF.Link | None
		no_of_employees: DF.Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"]
		organization_logo: DF.AttachImage | None
		organization_name: DF.Data | None
		territory: DF.Link | None
		website: DF.Data | None
	# end: auto-generated types

	def validate(self):
		from crm.permissions.customers import validate_account_owner_change

		validate_account_owner_change(self)
		self.update_exchange_rate()

	def after_insert(self):
		# A customer a rep adds is theirs. Written after insert, as the claim is the
		# system's: a rep has no write access to the (permlevel 1) field.
		from crm.permissions.customers import claim_if_unowned

		claim_if_unowned(self.name, frappe.session.user)

		# Auto-enrich a new Organization from its website (best-effort, background job).
		from crm.domain_enrichment.tasks import auto_enrich_on_create

		auto_enrich_on_create(self)

	def after_rename(self, old_name, new_name, merge=False):
		"""Carry the organization's contacts across a rename or a merge.

		A contact belongs to an organization through core's
		``Contact.company_name``, which is a Data field rather than a Link, so
		rename_doc does not rewrite it. Left behind, every contact pointed at a
		name that no longer exists and the org page's Contacts tab came up empty.
		"""
		frappe.db.set_value(
			"Contact",
			{"company_name": old_name},
			"company_name",
			new_name,
			update_modified=False,
		)

	def update_exchange_rate(self):
		"""Refresh the rate, but never let a third party decide whether the record saves.

		The same rule as ``CRMDeal.update_exchange_rate``: this runs inside
		``validate`` and ``get_exchange_rate`` throws when no provider answers, so
		a host without outbound internet failed every save of a foreign-currency
		organization. A stale rate is a wrong number in a report; an unsaveable
		organization is a rep who cannot file the visit they just made.
		"""
		if not (self.has_value_changed("currency") or not self.exchange_rate):
			return

		system_currency = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
		if not self.currency or self.currency == system_currency:
			self.db_set("exchange_rate", 1)
			return

		try:
			self.db_set("exchange_rate", get_exchange_rate(self.currency, system_currency))
		except Exception:
			# get_exchange_rate has already logged which provider failed
			if not self.exchange_rate:
				# a brand-new record has nothing to keep; 1 is the honest placeholder
				# that the warning below tells the person about
				self.db_set("exchange_rate", 1)
			frappe.msgprint(
				frappe._(
					"Could not fetch the {0} to {1} exchange rate. Saved with the previous rate."
				).format(self.currency, system_currency),
				indicator="orange",
				alert=True,
			)

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Organization",
				"type": "Data",
				"key": "organization_name",
				"width": "16rem",
			},
			{
				"label": "Customer Code",
				"type": "Data",
				"key": "acumatica_id",
				"width": "10rem",
			},
			{
				"label": "Website",
				"type": "Data",
				"key": "website",
				"width": "14rem",
			},
			{
				"label": "Industry",
				"type": "Link",
				"key": "industry",
				"options": "CRM Industry",
				"width": "14rem",
			},
			{
				"label": "Annual Revenue",
				"type": "Currency",
				"key": "annual_revenue",
				"width": "14rem",
			},
			{
				"label": "Account Owner",
				"type": "Link",
				"key": "account_owner",
				"options": "User",
				"width": "12rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"organization_name",
			"acumatica_id",
			"organization_logo",
			"website",
			"industry",
			"currency",
			"annual_revenue",
			"account_owner",
			"modified",
		]
		if not frappe.get_meta("CRM Organization").has_field("acumatica_id"):
			# the customer code is a custom field created on install and migrate; a
			# site caught between the two must still list its organizations
			columns = [c for c in columns if c["key"] != "acumatica_id"]
			rows.remove("acumatica_id")
		return {"columns": columns, "rows": rows}
