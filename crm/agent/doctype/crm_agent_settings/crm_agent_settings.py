# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document


class CRMAgentSettings(Document):
	def validate(self):
		self.validate_base_url()

	def validate_base_url(self):
		"""The base URL is the target of a server-side POST carrying the API key.

		An unchecked value here is an SSRF primitive with credential replay: a
		``file://`` or bare-host entry reaches whatever the worker can reach. Only
		http(s) with a host is accepted; the network the host resolves to is the
		administrator's call, but the scheme is not.
		"""
		if not self.base_url:
			return
		parsed = urlparse(self.base_url)
		if parsed.scheme not in ("http", "https") or not parsed.netloc:
			frappe.throw(_("Base URL must be an http:// or https:// address including a host."))
