"""Fill in each customer's head account from Acumatica, once.

MBP keeps a mine's plants and shafts as customers of their own under a head
account (Customer.ParentRecord). The sync now records it on every customer it
reads, but it reads only customers modified since its last run, so the sites
already imported would wait for an edit in Acumatica. This queues one read of
every customer's parent (``importer.link_head_accounts``, GETs only) on a site
with the integration on.

The field is permlevel 2, read by managers only; the doctype JSON carries those
rows. Custom DocPerm replaces a doctype's permissions wholesale, so a site that
customised CRM Organization's gets them here (same rule as
``grant_acumatica_identity_permlevel``). Idempotent.
"""

import frappe

DOCTYPE = "CRM Organization"
READERS = ("System Manager", "Sales Manager")


def _grant_level_two():
	if not frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE}):
		return
	for role in READERS:
		if frappe.db.exists("Custom DocPerm", {"parent": DOCTYPE, "role": role, "permlevel": 2}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 2,
				"read": 1,
			}
		).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=DOCTYPE)


def execute():
	# Patches run before after_migrate, which is what creates the custom fields.
	from crm.integrations.acumatica.install import ensure_custom_fields

	ensure_custom_fields()
	_grant_level_two()
	if not frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		return
	try:
		# On a worker after the migrate commits. frappe.enqueue runs the job inline
		# when redis is unreachable; a failed Acumatica read must not then fail the
		# migrate -- the job is safe to run again by hand.
		frappe.enqueue(
			"crm.integrations.acumatica.importer.link_head_accounts",
			queue="long",
			job_id="acumatica_link_head_accounts",
			deduplicate=True,
			enqueue_after_commit=True,
		)
	except Exception:
		frappe.log_error(title="Linking Acumatica head accounts failed; run it again by hand")
