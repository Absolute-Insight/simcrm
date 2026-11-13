"""Keep an ERP integration that already works on a private address working.

From this release the stored credentials are only sent to a public address, or to
a host listed in the ``crm_erp_trusted_hosts`` site-config key (see
``crm/integrations/remote_url.py``). A site that was already pointed at a
self-hosted ERP -- ``http://erpnext-frontend:8080``, a 192.168.x address -- would
otherwise lose its sync on the first request after the upgrade, with nothing in
the settings having changed.

So the hosts in the URLs saved *now* are grandfathered: each one that is internal
is added to the key. One that does not resolve from here is added as well -- not
resolving in the migrate container is no proof the workers cannot reach it, and
an integration silently stopped is the worse mistake. A host that resolves to a
public address needs no trust and gets none.

This runs inside ``bench migrate``, which is an operator's action: it is still the
case that no application role can grant trust. Hosts already listed are kept, none
is repeated, and a second run changes nothing.
"""

import frappe
from frappe.installer import update_site_config

from crm.integrations.remote_url import TRUSTED_HOSTS_KEY, host_state, origin

SAVED_URLS = (
	("CRM Acumatica Settings", "instance_url", "Acumatica Instance URL"),
	("ERPNext CRM Settings", "erpnext_site_url", "SIMERP Site URL"),
)
GRANDFATHERED = ("internal", "unresolved")


def execute():
	configured = frappe.conf.get(TRUSTED_HOSTS_KEY) or []
	if isinstance(configured, str):
		configured = configured.split(",")
	hosts = [str(host).strip() for host in configured if str(host).strip()]
	listed = {host.lower().rstrip(".") for host in hosts}

	added = []
	for doctype, field, label in SAVED_URLS:
		url = (frappe.db.get_single_value(doctype, field, cache=False) or "").strip()
		if not url:
			continue
		parts = origin(url)
		if parts is None:
			_log(f"{label} is not an http(s) URL and was left alone; nothing was trusted for it")
			continue
		host = parts[1]
		state = host_state(host)
		if state not in GRANDFATHERED or host in listed:
			continue
		reason = "is on a private address" if state == "internal" else "did not resolve during the upgrade"
		_log(f"trusted {host} ({label}): it {reason}, and is already in use")
		added.append(host)
		listed.add(host)

	if not added:
		return
	hosts += added
	update_site_config(TRUSTED_HOSTS_KEY, hosts, validate=False)
	# the rest of this migrate, and the test that reads it back, see it at once
	frappe.local.conf[TRUSTED_HOSTS_KEY] = hosts


def _log(message: str) -> None:
	message = f"{TRUSTED_HOSTS_KEY}: {message}"
	frappe.logger("crm.integrations").warning(message)
	print(message)  # migrate's own output, where the operator is looking
