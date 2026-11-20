# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Move a site off the retired model server, where it never chose another.

Until v3.36 the product's default model was Liquid AI's ``LFM2.5-2.6B``, served
by a compose profile (``local-model``) that no longer exists. A doctype default
only fills a row that is being created, so a site whose settings were saved --
or seeded by ``create-site`` -- still stores the old name and the old address,
and after this upgrade would go on asking a service that is gone for a model
nothing here ships.

The fingerprint is both values at once, each *exactly* what this app shipped:
the model name, and ``http://ollama:11434/v1`` -- the removed profile's own
service, written by the compose file's default. Together they say the site was
on the stack's model server and nobody decided otherwise. Either one alone does
not: an endpoint an admin entered is their server, and the model it serves is
theirs to name, the retired one included. Another model, the same model under
another tag or quantisation, a trailing slash, ``localhost`` -- all were typed
by someone, and the whole row stays as it is.

Where the fingerprint matches, the site is moved to the model server the stack
ships now, and two settings that were entered for the old one go with it:

- ``reasoning_off`` goes back to 0. The old model ignored the request and
  thought regardless, so the switch could sit on and mean nothing. The new one
  obeys it, and is measured to resist the injection corpus with its thinking on
  and not with it off (deploy/README.md, the 2026-11-16 measurement).
- A stored ``api_key`` is removed. It was entered for another endpoint, and the
  client would send it to this one as a bearer token.

A Single that was never saved has nothing stored, reads the code defaults, and
needs nothing from this patch.
"""

import frappe
from frappe.utils.password import remove_encrypted_password

from crm.agent.config import DEFAULT_SETTINGS

SETTINGS = "CRM Agent Settings"

# Every default the app has shipped for the retired model: the bare tag of the
# first release and the ollama reference that replaced it.
RETIRED_MODELS = ("hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M", "lfm2.5-2.6b")
RETIRED_BASE_URL = "http://ollama:11434/v1"
# What deploy/docker-compose.yml seeds a new site with: the `llm` service.
STACK_BASE_URL = "http://llm:8086/v1"


def _has_stored_key() -> bool:
	"""Whether a key is on file, without decrypting it."""
	return bool(
		frappe.db.sql(
			"select 1 from `__Auth` where doctype = %s and name = %s and fieldname = %s limit 1",
			(SETTINGS, SETTINGS, "api_key"),
		)
	)


def execute():
	stored = frappe.db.get_singles_dict(SETTINGS)
	if stored.get("model") not in RETIRED_MODELS or stored.get("base_url") != RETIRED_BASE_URL:
		return

	moved = {"model": DEFAULT_SETTINGS["model"], "base_url": STACK_BASE_URL}
	changes = [f"model {stored.get('model')!r} -> {moved['model']!r}", f"base_url -> {STACK_BASE_URL!r}"]

	if str(stored.get("reasoning_off") or "0").strip() not in ("0", "0.0"):
		moved["reasoning_off"] = 0
		changes.append("reasoning_off -> 0")

	had_key = _has_stored_key()
	if had_key or stored.get("api_key"):
		# The Singles row holds only the mask; the secret itself is in __Auth.
		remove_encrypted_password(SETTINGS, SETTINGS, "api_key")
		moved["api_key"] = ""
		changes.append("api_key removed (it was entered for the old endpoint)")

	for field, value in moved.items():
		frappe.db.set_single_value(SETTINGS, field, value)
	frappe.clear_cache(doctype=SETTINGS)

	frappe.logger("crm.agent").warning(
		"CRM Agent Settings pointed at the removed local-model service with its default model;"
		f" moved to the stack's model server: {'; '.join(changes)}. The tier reports"
		" 'unavailable' until that endpoint serves the model -- see deploy/README.md,"
		" 'Moving a host from the local-model profile'."
	)
