# Copyright (c) 2026, Absolute Insight and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMWhatsAppLine(Document):
	"""One WhatsApp number: which rep it belongs to, and the App Secret that
	proves a webhook for it came from Meta.

	``whatsapp_account`` is a Dynamic Link over a fixed hidden doctype rather
	than a Link because frappe_whatsapp is optional and this doctype is not: a
	Link to a doctype a site does not have fails that site's test-record walk.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account_doctype: DF.Link | None
		app_secret: DF.Password | None
		user: DF.Link | None
		whatsapp_account: DF.DynamicLink
	# end: auto-generated types

	def validate(self):
		if not frappe.db.exists("DocType", "WhatsApp Account"):
			frappe.throw(_("Install frappe_whatsapp before adding a WhatsApp line."))
		self.account_doctype = "WhatsApp Account"
