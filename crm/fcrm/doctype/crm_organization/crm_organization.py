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
		self.update_exchange_rate()

	def after_insert(self):
		# Auto-enrich a new Organization from its website (best-effort, background job).
		from crm.domain_enrichment.tasks import auto_enrich_on_create

		auto_enrich_on_create(self)

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
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"organization_name",
			"organization_logo",
			"website",
			"industry",
			"currency",
			"annual_revenue",
			"modified",
		]
		return {"columns": columns, "rows": rows}
