# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document

# What the shipped compose stack sets on nginx (`PROXY_READ_TIMEOUT: 120`). A
# deployment that raised it says so with `crm_proxy_read_timeout` in site config.
DEFAULT_PROXY_READ_TIMEOUT = 120


class CRMAgentSettings(Document):
	def validate(self):
		self.validate_base_url()
		self.validate_timeout()

	def validate_timeout(self):
		"""One call can cost ``timeout x 2``; that has to fit inside the proxy.

		``client.MAX_ATTEMPTS`` is 2, so a request occupies a *web* worker for up
		to twice this before it gives up. Set 300 against the shipped
		``PROXY_READ_TIMEOUT`` of 120 and nginx hangs up at 120: the rep sees a
		failed request while the worker keeps going for another 480 seconds, and
		nothing in the CRM explains why.

		Refused at save rather than clamped quietly. A clamp would leave the form
		showing a number the system is not using, which is the same class of
		dishonesty as the failure it prevents.
		"""
		if not self.timeout:
			return

		proxy_timeout = frappe.conf.get("crm_proxy_read_timeout") or DEFAULT_PROXY_READ_TIMEOUT
		try:
			proxy_timeout = int(proxy_timeout)
		except (TypeError, ValueError):
			proxy_timeout = DEFAULT_PROXY_READ_TIMEOUT

		limit = (proxy_timeout - 1) // 2
		if int(self.timeout) > limit:
			frappe.throw(
				_(
					"Timeout must be at most {0} seconds. A call retries once, so it can hold a"
					" web worker for twice this, and your proxy gives up at {1} seconds — the"
					" request would fail while the worker kept running. Raise the proxy's read"
					" timeout and set crm_proxy_read_timeout in site config to match if you need"
					" a slower model."
				).format(limit, proxy_timeout),
				title=_("Timeout exceeds the proxy's limit"),
			)

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
