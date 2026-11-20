# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Move a site off the retired default model, where it never chose one.

Until v3.36 the product's default model was Liquid AI's ``LFM2.5-2.6B``, served
by a compose profile (``local-model``) that no longer exists. A doctype default
only fills a row that is being created, so a site whose settings were saved --
or seeded by ``create-site`` -- still stores the old name, and after this
upgrade would go on asking its endpoint for a model nothing here ships.

Only a value that is *exactly* a default this app once shipped is replaced: it
carries no decision of the admin's. Anything else -- another model, the same
model under another tag or quantisation -- was typed by someone, and stays.

The endpoint moves with it under the same rule, and only together with the
model: ``http://ollama:11434/v1`` was the removed profile's service, written by
the compose file's own default, and with the profile gone it names nothing.
Left in place it would leave the new model name pointed at a host that does not
resolve. An endpoint an admin entered, including ``localhost``, is not touched,
and neither is one whose model was not ours to change.

A Single that was never saved has nothing stored, reads the code defaults, and
needs nothing from this patch.
"""

import frappe

from crm.agent.config import DEFAULT_SETTINGS

SETTINGS = "CRM Agent Settings"

# Every default the app has shipped for the retired model: the bare tag of the
# first release and the ollama reference that replaced it.
RETIRED_MODELS = ("hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M", "lfm2.5-2.6b")
RETIRED_BASE_URL = "http://ollama:11434/v1"
# What deploy/docker-compose.yml seeds a new site with: the `llm` service.
STACK_BASE_URL = "http://llm:8086/v1"


def execute():
	stored = frappe.db.get_singles_dict(SETTINGS)
	if stored.get("model") not in RETIRED_MODELS:
		return

	moved = {"model": DEFAULT_SETTINGS["model"]}
	if stored.get("base_url") == RETIRED_BASE_URL:
		moved["base_url"] = STACK_BASE_URL

	for field, value in moved.items():
		frappe.db.set_single_value(SETTINGS, field, value)
	frappe.clear_cache(doctype=SETTINGS)

	frappe.logger("crm.agent").warning(
		f"CRM Agent Settings: the stored model {stored.get('model')!r} was the retired default;"
		f" replaced {sorted(moved)} with {moved}. The tier reports 'unavailable' until that"
		" endpoint serves the model -- see deploy/README.md, 'Moving a host from the"
		" local-model profile'."
	)
