import json
import re

import frappe
import requests
from frappe import _
from frappe.utils.background_jobs import is_job_enqueued

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	dismiss_sync_issues,
	get_pending_retries,
	get_settings,
)
from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v

# Both describe the sync rather than this button -- the timeout is how long one takes,
# and the job id is shared with the sweep and the webhook so only one can be queued --
# so they live with the importer.
from crm.integrations.acumatica.importer import BACKFILL_TIMEOUT, SYNC_JOB_ID


@frappe.whitelist(methods=["POST"])
def start_backfill() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	if not settings.enabled:
		frappe.throw(_("Enable the Acumatica integration first"))
	frappe.enqueue(
		"crm.integrations.acumatica.importer.run_backfill",
		queue="long",
		job_id=SYNC_JOB_ID,
		deduplicate=True,
		timeout=BACKFILL_TIMEOUT,
	)
	return {"queued": True}


@frappe.whitelist()
def get_sync_status() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	open_issues = sum(1 for row in settings.sync_issues if not row.dismissed)
	# a count, not the queue itself -- the retry list is a work list for the sweep,
	# not something the panel walks entity by entity
	pending_retries = sum(len(attempts) for attempts in get_pending_retries().values())
	return {
		"last_synced_at": settings.last_synced_at,
		"open_issues": open_issues,
		"running": is_job_enqueued(SYNC_JOB_ID),
		"last_sync_error": settings.last_sync_error,
		"pending_retries": pending_retries,
	}


# POST only, like everything here that acts: frappe skips the CSRF check on a GET, so
# a link or an <img> in a page the admin opens could fire it on their session.
@frappe.whitelist(methods=["POST"])
def test_connection() -> dict:
	"""Never raises: a transport failure is exactly what an admin clicking this button
	is trying to see, not a stack trace on the panel."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_doc("CRM Acumatica Settings")  # the saved doc -- the operator just saved it
	if not settings.instance_url:
		return {"ok": False, "error": _("Instance URL is required")}
	# Its own login, never the shared cached one: the operator may have just changed
	# the credentials, and a cached token from the old ones would test those. Deleting
	# the shared key instead did not end that login -- a running sync minted another,
	# and the one dropped from the cache held an API login slot until it expired.
	client = AcumaticaClient(settings, shared_session=False)
	try:
		return client.ping()
	except AcumaticaError as e:
		if e.status_code:
			error = f"{e.status_code}: {e.detail(300)}"
		else:
			error = str(e)
		return {"ok": False, "error": error}
	except Exception as e:
		return {"ok": False, "error": str(e)}
	finally:
		# one click, one login, released -- not a session held for an hour
		client.logout()


@frappe.whitelist()
def get_open_sync_issues() -> list[dict]:
	"""The counter alone tells an admin something broke but not what."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	return [
		{
			"name": issue.name,
			"entity": issue.entity,
			"remote_id": issue.remote_id,
			"kind": issue.kind,
			"detail": issue.detail,
			"candidates": _candidates(issue),
			"detected_on": issue.detected_on,
		}
		for issue in settings.sync_issues
		if not issue.dismissed
	]


def _candidates(issue) -> list[dict]:
	"""A Possible Duplicate row's candidates; [] for every other row, or one whose JSON
	does not read."""
	raw = issue.get("candidates")
	if not raw:
		return []
	try:
		data = json.loads(raw) if isinstance(raw, str) else raw
	except ValueError:
		return []
	return data if isinstance(data, list) else []


@frappe.whitelist(methods=["POST"])
def dismiss_sync_issue(issue_name: str | int) -> bool:
	"""Child rows autoincrement, so ``get_open_sync_issues`` hands the panel an int and
	the panel posts it back as a JSON number. A bare ``str`` annotation made Frappe's
	argument validation answer 417 to every real Dismiss click."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_doc("CRM Acumatica Settings")
	for issue in settings.sync_issues:
		# an int from the panel, a string from anything that stringified it first
		if str(issue.name) == str(issue_name):
			issue.dismissed = 1
			# clearing a log row must not be blocked by the config validations
			settings.flags.ignore_validate = True
			settings.save(ignore_permissions=True)
			return True
	return False


@frappe.whitelist()
def is_enabled() -> bool:
	"""The one bit the Deal form script needs. The settings document itself holds the
	webhook secret and the API identity, so reps get this and nothing else."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return bool(frappe.db.get_single_value("CRM Acumatica Settings", "enabled"))


@frappe.whitelist()
def get_crm_form_script():
	"""Form Script for CRM Deal -- same delivery mechanism as the ERPNext
	integration's get_crm_form_script. Additive only: it registers an action,
	it does not touch existing helpers."""
	return """class CRMDeal {
	onLoad() {
		if (this.doc.__newDocument) return
		call("crm.integrations.acumatica.api.is_enabled").then((enabled) => {
			if (enabled) this.doc.trigger("setAcumaticaActions")
		}).catch(() => {})
	}
	setAcumaticaActions() {
		// One quote per deal: the server refuses a second one anyway, so a deal
		// that already carries its quote number gets no button rather than a
		// button that only ever produces an error.
		if (this.doc.acumatica_sales_quote) return
		// The action button has no pending state of its own, and the server round
		// trip is a PUT into the client's ERP: a second click while the first is in
		// flight must be ignored, not sent.
		let pending = false
		this.actions.push({
			label: __("Create Sales Quote"),
			onClick: () => {
				if (pending) {
					toast.info(__("Sales quote creation is already in progress"))
					return
				}
				pending = true
				call("crm.integrations.acumatica.outbound.create_sales_quote_from_deal", {
					crm_deal: this.doc.name,
				}).then((order_nbr) => {
					toast.success(__("Sales quote {0} created in Acumatica", [order_nbr]))
				}).catch((e) => {
					toast.error(e.messages?.[0] || __("Error while creating sales quote in Acumatica. Check error log for more details"))
				}).finally(() => {
					pending = false
				})
			},
		})
	}
}"""


# Acumatica's CUSTOMER ID segment: letters, digits and the separators tenants put in
# them (C-A00403). Anything else is not a code this would ever hold, and never reaches
# an OData filter.
CUSTOMER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]{0,29}$")
_RESOLVED = ("Possible Duplicate", "Push Blocked")


def _unlinked_organization(organization: str):
	"""The organization a manager is resolving, checked: it exists, they may edit it,
	and the integration is in a state to act on."""
	if not get_settings().enabled:
		frappe.throw(_("The Acumatica integration is not enabled"))
	if not isinstance(organization, str) or not frappe.db.exists("CRM Organization", organization):
		frappe.throw(_("Organization not found"), frappe.DoesNotExistError)
	frappe.has_permission("CRM Organization", "write", doc=organization, throw=True)
	return frappe.db.get_value(
		"CRM Organization",
		organization,
		["name", "acumatica_id", "acumatica_noteid"],
		as_dict=True,
		for_update=True,
	)


# POST only, managers only: both write an organization's Acumatica identity, which
# decides whether a customer is created in the client's ERP.
@frappe.whitelist(methods=["POST"])
def link_existing_customer(organization: str, customer_id: str) -> dict:
	"""A possible duplicate was right: link the organization to that customer instead
	of creating one."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	customer_id = (customer_id or "").strip() if isinstance(customer_id, str) else ""
	if not CUSTOMER_ID.match(customer_id):
		frappe.throw(_("That is not an Acumatica customer code"))
	org = _unlinked_organization(organization)
	if org.acumatica_id and org.acumatica_id != customer_id:
		frappe.throw(
			_("This organization is already linked to Acumatica customer {0}").format(org.acumatica_id)
		)
	holder = frappe.db.get_value(
		"CRM Organization", {"acumatica_id": customer_id, "name": ("!=", org.name)}, "name"
	)
	if holder:
		frappe.throw(
			_(
				"Customer {0} is already linked to organization {1}. Move the deal to {1} instead of linking a second organization to it."
			).format(customer_id, frappe.utils.escape_html(holder))
		)

	from crm.integrations.acumatica.outbound import _odata, _reason

	try:
		page = AcumaticaClient(get_settings()).get_page(
			"Customer",
			top=1,
			filter=f"CustomerID eq {_odata(customer_id)}",
			select="CustomerID,CustomerName,NoteID",
			orderby=None,
		)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		frappe.throw(_("Could not check the customer in Acumatica: {0}").format(_reason(e)))
	if not page:
		frappe.throw(_("Acumatica has no customer {0}").format(customer_id))

	noteid = v(page[0], "NoteID")
	frappe.db.set_value(
		"CRM Organization",
		org.name,
		{"acumatica_id": customer_id, "acumatica_noteid": noteid or org.acumatica_noteid},
	)
	frappe.db.set_value(
		"CRM Deal",
		{"organization": org.name, "acumatica_customer": ("is", "not set")},
		"acumatica_customer",
		customer_id,
	)
	dismiss_sync_issues("Customer", org.name, _RESOLVED)
	return {"organization": org.name, "customer_id": customer_id}


@frappe.whitelist(methods=["POST"])
def confirm_new_customer(organization: str) -> dict:
	"""A manager looked at the possible duplicates and this is a new customer: push it,
	skipping the name and email checks. A same-VAT match is not something to confirm
	past -- one taxpayer is one customer -- so it is refused here too."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	org = _unlinked_organization(organization)
	if org.acumatica_id or org.acumatica_noteid:
		frappe.throw(_("This organization is already linked to an Acumatica customer"))
	settings = get_settings()
	# the stored rows, not the cached doc: the issue may have been written a moment ago
	for issue in frappe.get_doc("CRM Acumatica Settings").sync_issues:
		if issue.dismissed or issue.remote_id != org.name or issue.kind != "Possible Duplicate":
			continue
		if any("same VAT number" in (c.get("reasons") or []) for c in _candidates(issue)):
			frappe.throw(
				_(
					"An Acumatica customer has the same VAT number. Link to it, or correct the VAT number first."
				)
			)

	frappe.db.set_value("CRM Organization", org.name, "acumatica_confirmed_new", 1)
	dismiss_sync_issues("Customer", org.name, ("Possible Duplicate",))
	queued = False
	if settings.create_customer_on_status_change and settings.deal_status:
		deal = frappe.db.get_value(
			"CRM Deal", {"organization": org.name, "status": settings.deal_status}, "name"
		)
		if deal:
			from crm.integrations.acumatica.outbound import _enqueue_push

			_enqueue_push(deal, org.name)
			queued = True
	return {"organization": org.name, "queued": queued}
