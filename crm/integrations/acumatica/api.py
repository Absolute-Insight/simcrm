import json
import re

import frappe
import requests
from frappe import _
from frappe.utils.background_jobs import is_job_enqueued

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	dismiss_sync_issue_row,
	dismiss_sync_issues,
	get_pending_retries,
	get_settings,
	open_sync_issues,
)
from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v

# Both describe the sync rather than this button -- the timeout is how long one takes,
# and the job id is shared with the sweep and the webhook so only one can be queued --
# so they live with the importer.
from crm.integrations.acumatica.importer import BACKFILL_TIMEOUT, SYNC_JOB_ID
from crm.permissions.customers import customer_visible, scope_applies


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
	# a count, not the queue itself -- the retry list is a work list for the sweep,
	# not something the panel walks entity by entity
	pending_retries = sum(len(attempts) for attempts in get_pending_retries().values())
	if scope_applies():
		# the same rows get_open_sync_issues shows them, and no free text: the run's
		# last error may name any customer
		return {
			"last_synced_at": settings.last_synced_at,
			"open_issues": sum(1 for row in settings.sync_issues if _visible_row(row)),
			"running": is_job_enqueued(SYNC_JOB_ID),
			"last_sync_error": _("The last sync stopped with an error.") if settings.last_sync_error else "",
			"pending_retries": pending_retries,
		}
	return {
		"last_synced_at": settings.last_synced_at,
		"open_issues": sum(1 for row in settings.sync_issues if not row.dismissed),
		"running": is_job_enqueued(SYNC_JOB_ID),
		"last_sync_error": settings.last_sync_error,
		"pending_retries": pending_retries,
	}


def _visible_row(row) -> bool:
	"""For a scoped manager: an open row about an organization they can see."""
	if row.dismissed:
		return False
	owner = _issue_organization(row)
	return bool(owner) and customer_visible(owner)


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
		# The status and a fixed sentence, never the reply: the URL is whatever a
		# Sales Manager saved, and relaying the body made this button a way to read
		# the first lines of any page that URL serves. The reply goes to the Error
		# Log, where a System Manager finds it.
		if e.status_code and 300 <= int(e.status_code) < 400:
			# not followed: the login would be re-posted to wherever it points
			error = _(
				"{0}: the Instance URL answered with a redirect. Enter the address the "
				"instance answers on directly."
			).format(e.status_code)
		elif e.status_code:
			_log_test_failure(f"{e}\n\n{e.detail(1000)}")
			error = _("{0}: Acumatica refused the request. The reply is in the Error Log.").format(
				e.status_code
			)
		else:
			error = str(e)  # raised by the client itself, in its own words
		return {"ok": False, "error": error}
	except Exception as e:
		# requests' own text names the address and says whether the port answered
		_log_test_failure(frappe.get_traceback())
		return {"ok": False, "error": _connection_failure(e)}
	finally:
		# one click, one login, released -- not a session held for an hour
		client.logout()


def _log_test_failure(detail: str) -> None:
	frappe.log_error(title="Acumatica test connection failed", message=detail)


def _connection_failure(exc: Exception) -> str:
	"""What kind of failure it was, in a sentence of ours."""
	if isinstance(exc, requests.exceptions.Timeout):
		return _("The Acumatica instance did not answer in time.")
	if isinstance(exc, requests.exceptions.SSLError):
		return _("The Acumatica instance's certificate could not be verified.")
	if isinstance(exc, requests.exceptions.ConnectionError | ConnectionError):
		return _("Could not connect to the Acumatica instance. Check the Instance URL.")
	return _(
		"The Acumatica instance gave an answer that could not be read. The details are in the Error Log."
	)


@frappe.whitelist()
def get_open_sync_issues() -> list[dict]:
	"""The counter alone tells an admin something broke but not what.

	A manager whose customers are scoped (an in-tree manager, or one outside the tree
	kept to their own records) gets a filtered view that fails closed: a row is shown
	only when the organization it is about resolves and is one they can see, a
	candidate only when it is no organization here or one they can see, and the free
	text only where nothing in it can name somebody else's customer."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	scoped = scope_applies()
	out = []
	for issue in settings.sync_issues:
		if issue.dismissed:
			continue
		detail = issue.detail
		candidates = _candidates(issue)
		if scoped:
			if not _visible_row(issue):
				continue
			candidates = [
				c for c in candidates if not c.get("organization") or customer_visible(c["organization"])
			]
			detail = _scoped_detail(issue, candidates)
		out.append(
			{
				"name": issue.name,
				"entity": issue.entity,
				"remote_id": issue.remote_id,
				"kind": issue.kind,
				"detail": detail,
				"candidates": candidates,
				"detected_on": issue.detected_on,
			}
		)
	return out


def _issue_organization(issue) -> str | None:
	"""The organization a row is about, or None when it cannot be told -- which hides
	the row from a scoped manager."""
	remote_id = issue.remote_id
	if not remote_id:
		return None
	if issue.entity in ("Customer", "Customer Salesperson"):
		return remote_id if frappe.db.exists("CRM Organization", remote_id) else None
	if issue.entity == "Contact":
		company = frappe.db.get_value("Contact", remote_id, "company_name")
		return company if company and frappe.db.exists("CRM Organization", company) else None
	if issue.entity == "Deal":
		return frappe.db.get_value("CRM Deal", remote_id, "organization") or None
	return None


def _scoped_detail(issue, candidates: list[dict]) -> str:
	"""The detail a scoped manager may read. The push's own messages name other
	organizations (a candidate, the holder of a colliding code), and an Acumatica
	error may quote anything, so only what is rebuilt from visible facts is kept."""
	if issue.kind == "Push Blocked":
		# the gate's list of what is missing names nothing but fields
		return issue.detail
	if issue.kind == "Possible Duplicate":
		if not candidates:
			return _("not created in Acumatica: it may already be an existing customer.")
		from crm.integrations.acumatica.outbound import _describe

		return _("not created in Acumatica: may already be {0}.").format(_describe(candidates))
	return _("{0}: the details are shown to a manager who sees every customer.").format(_(issue.kind))


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
	argument validation answer 417 to every real Dismiss click. The row alone is
	written -- never the whole Single, which a job may be writing at the same time."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	try:
		name = int(issue_name)
	except (TypeError, ValueError):
		return False
	if scope_applies():
		# only a row they were shown: the id is a counter, easy to walk
		row = frappe.db.get_value(
			"CRM Acumatica Sync Issue",
			{"name": name, "parent": "CRM Acumatica Settings"},
			["name", "entity", "remote_id", "dismissed"],
			as_dict=True,
		)
		if not row or not _visible_row(row):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	return dismiss_sync_issue_row(name)


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
_RESOLVED = ("Possible Duplicate", "Push Blocked", "Push Failed")


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
		["name", "acumatica_id", "acumatica_noteid", "acumatica_confirmed_for"],
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
		_refuse_held(customer_id, holder)

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
	if noteid:
		# the same customer held under its NoteID alone (a sync that saw it renamed)
		holder = frappe.db.get_value(
			"CRM Organization", {"acumatica_noteid": noteid, "name": ("!=", org.name)}, "name"
		)
		if holder:
			_refuse_held(customer_id, holder)
	frappe.db.set_value(
		"CRM Organization",
		org.name,
		{"acumatica_id": customer_id, "acumatica_noteid": noteid or org.acumatica_noteid},
	)
	# Every deal of the organization without a quote number gets the code, whatever it
	# held: Create Sales Quote prefers the deal's code to the organization's. One with
	# a quote is left as it is -- its quote was raised under that code.
	frappe.db.set_value(
		"CRM Deal",
		{"organization": org.name, "acumatica_sales_quote": ("is", "not set")},
		"acumatica_customer",
		customer_id,
	)
	dismiss_sync_issues("Customer", org.name, _RESOLVED)
	return {"organization": org.name, "customer_id": customer_id}


def _refuse_held(customer_id: str, holder: str) -> None:
	if scope_applies():
		# which organization holds it may be a customer this manager cannot see
		frappe.throw(
			_(
				"Customer {0} is already linked to another organization. Move the deal to that organization instead of linking a second one to it."
			).format(customer_id)
		)
	frappe.throw(
		_(
			"Customer {0} is already linked to organization {1}. Move the deal to {1} instead of linking a second organization to it."
		).format(customer_id, frappe.utils.escape_html(holder))
	)


@frappe.whitelist(methods=["POST"])
def confirm_new_customer(organization: str) -> dict:
	"""A manager looked at the possible duplicates and this is a new customer -- a
	same-VAT match included, since one taxpayer can hold several accounts (MBP keeps
	branches apart). What they confirmed is recorded as a fingerprint of the name,
	VAT number and primary-contact email (outbound.confirmation_hash) of the deal
	waiting on it: the push skips the duplicate checks only while the organization
	still matches it."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	org = _unlinked_organization(organization)
	if org.acumatica_id or org.acumatica_noteid:
		frappe.throw(_("This organization is already linked to an Acumatica customer"))
	# confirmed past the candidates the manager was shown, and only those: one that
	# turns up later still blocks
	candidates = [
		c
		for issue in open_sync_issues("Customer", org.name, ("Possible Duplicate",))
		for c in _candidates(issue)
	]
	if scope_applies() and any(
		c.get("organization") and not customer_visible(c["organization"]) for c in candidates
	):
		# get_open_sync_issues hid that candidate from them; they cannot confirm past
		# what they were never shown
		frappe.throw(
			_("This may be a customer you cannot see. A manager who can see all customers must review it."),
			frappe.PermissionError,
		)
	settings = get_settings()
	if not (settings.create_customer_on_status_change and settings.deal_status):
		frappe.throw(_("Creating customers in Acumatica is switched off"))
	deal = frappe.db.get_value("CRM Deal", {"organization": org.name, "status": settings.deal_status}, "name")
	if not deal:
		frappe.throw(_("No deal of this organization is waiting to create it in Acumatica"))

	from crm.integrations.acumatica.outbound import (
		_confirmed_past,
		_customer_facts,
		_enqueue_push,
		confirmation_value,
	)

	facts = _customer_facts(
		frappe.get_doc("CRM Deal", deal), frappe.get_doc("CRM Organization", org.name), settings
	)
	if facts.missing:
		frappe.throw(_("Complete the organization first: missing {0}").format(", ".join(facts.missing)))
	# Merged with what was confirmed past before, while the facts still match: the push
	# leaves already-confirmed codes out of a new row, so replacing `past` with this
	# row's candidates would drop the earlier ones and block on them again -- and a
	# second confirm with nothing open would wipe them.
	shown = sorted(
		{c.get("customer_id") for c in candidates if c.get("customer_id")}
		| set(_confirmed_past(org.get("acumatica_confirmed_for") or "", facts))
	)
	frappe.db.set_value(
		"CRM Organization",
		org.name,
		"acumatica_confirmed_for",
		confirmation_value(facts, shown),
		update_modified=False,
	)
	dismiss_sync_issues("Customer", org.name, ("Possible Duplicate",))
	# A job of its own: one already running for this organization would swallow a
	# deduplicated enqueue under the ordinary id -- and, having read the organization
	# before this, report the duplicate all over again.
	_enqueue_push(deal, org.name, job_suffix="_confirm")
	return {"organization": org.name, "queued": True}
