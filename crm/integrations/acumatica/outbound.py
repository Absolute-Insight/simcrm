import hashlib
import json
import re
import time

import frappe
import requests
from frappe import _
from frappe.query_builder.functions import Max
from frappe.utils import add_days, cint, now_datetime

from crm.agent.doctype.crm_agent_settings.crm_agent_settings import DEFAULT_PROXY_READ_TIMEOUT
from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	dismiss_sync_issues,
	get_settings,
	open_sync_issues,
	upsert_sync_issue,
)
from crm.integrations.acumatica.client import TIMEOUT, AcumaticaClient, AcumaticaError, v, wrap
from crm.integrations.acumatica.matching import name_match, normalise_name, normalise_vat, state_code

# A write Acumatica never answered may still have landed, and SalesOrder -- like a
# Customer under AutoNumber -- is a PUT with no key in the body: sending it again makes
# a second record in the client's ERP. So a write leaves a marker until its outcome is
# known, and the next attempt looks for what the unanswered one made before it sends
# anything. In redis, not the database: the request or job that set it is the one that
# is rolled back, or killed, when the answer never comes. hooks.persistent_cache_keys
# keeps frappe.clear_cache() off it.
INFLIGHT_PREFIX = "acumatica_inflight::"
INFLIGHT_TTL = 30 * 24 * 3600
# How long Acumatica may still be working on a quote after we stopped waiting for it.
# Inside this, finding no order proves nothing yet.
QUOTE_SETTLE_SECONDS = 300


def _inflight_key(entity: str, name: str) -> str:
	return f"{INFLIGHT_PREFIX}{entity}::{name}"


def _mark_inflight(key: str, value=None) -> None:
	frappe.cache().set_value(key, value or time.time(), expires_in_sec=INFLIGHT_TTL)


def _settle_inflight(key: str) -> None:
	"""The write's outcome is on record -- once it is committed. A rollback after a
	successful PUT (a worker killed before its commit) must leave the marker, so the
	next attempt finds the record instead of making another."""
	frappe.db.after_commit.add(lambda: frappe.cache().delete_value(key))


def _outcome_unknown(e) -> bool:
	"""Whether a failed write may have landed anyway. An error status from Acumatica
	is its answer: the write was refused. A timeout, a dropped connection, a gateway
	in front of it answering 502/503/504, or a body that is not JSON is no answer."""
	if isinstance(e, AcumaticaError) and e.status_code:
		return e.status_code in (502, 503, 504)
	return True


def _odata(value) -> str:
	"""A $filter string literal: OData doubles an embedded single quote."""
	return "'" + str(value).replace("'", "''") + "'"


def _push_switched_on(settings) -> bool:
	return bool(settings.enabled and settings.create_customer_on_status_change and settings.deal_status)


def _enqueue_push(deal: str, organization: str, job_suffix: str = "") -> None:
	frappe.enqueue(
		"crm.integrations.acumatica.outbound.push_customer_for_deal",
		deal=deal,
		queue="short",
		job_id=f"acumatica_customer_{organization}{job_suffix}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def _commit() -> None:
	"""A customer now exists in the client's ERP and its link is written: make that
	durable before anything else in the job can fail and roll it back. The follow-ups
	(contact, salesperson, issue rows) run after this and only ever record issues."""
	frappe.db.commit()  # nosemgrep: frappe-manual-commit


# The kinds an organization's push leaves behind until somebody acts.
PUSH_BLOCKED = "Push Blocked"
POSSIBLE_DUPLICATE = "Possible Duplicate"
PUSH_FAILED = "Push Failed"
WAITING_KINDS = (PUSH_BLOCKED, POSSIBLE_DUPLICATE)


def queue_customer_push(doc, method):
	"""CRM Deal on_update handler. Mirrors the ERPNext integration's trigger shape:
	fires once when the deal reaches the configured status. Cheap checks only --
	the HTTP PUT itself runs off-thread in push_customer_for_deal so a slow or
	down Acumatica never holds up the user's save."""
	if frappe.flags.in_demo_seed:
		# demo data's Won deals must not become customers in a real ERP
		return
	settings = get_settings()
	if not settings.enabled or not settings.create_customer_on_status_change or not doc.organization:
		return
	if doc.status != settings.deal_status:
		before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
		if (
			before
			and before.status == settings.deal_status
			and not frappe.db.exists(
				"CRM Deal",
				{"organization": doc.organization, "status": settings.deal_status, "name": ("!=", doc.name)},
			)
		):
			# the organization's last deal left the trigger status: nothing is waiting on
			# a manager or a rep for it any more
			dismiss_sync_issues("Customer", doc.organization, WAITING_KINDS)
		return
	_enqueue_push(doc.name, doc.organization)


def queue_customer_push_for_organization(doc, method):
	"""CRM Organization on_update handler: a push blocked on this organization's
	address or name tries again once a rep has fixed it. Only an organization with a
	push actually waiting on it -- an open Push Blocked or Possible Duplicate row --
	is re-queued: editing an unlinked organization with a years-old won deal must not
	be what creates it as a live customer. The identity test needs no read at all,
	and it is what turns away every save the sync itself makes."""
	if frappe.flags.in_demo_seed or doc.get("acumatica_noteid") or doc.get("acumatica_id"):
		return
	settings = get_settings()
	if not _push_switched_on(settings):
		return
	if not open_sync_issues("Customer", doc.name, WAITING_KINDS):
		return
	deal = frappe.db.get_value("CRM Deal", {"organization": doc.name, "status": settings.deal_status}, "name")
	if deal:
		_enqueue_push(deal, doc.name)


def create_customer_in_acumatica(doc, method):
	"""Deprecated: renamed to queue_customer_push. Kept as a thin alias for one
	release so a site with a stale hooks cache (pointing at the old dotted path)
	does not error before it picks up the new hooks.py."""
	return queue_customer_push(doc, method)


# The sweep re-tries what nothing else re-triggers (an Address or a Contact edited on
# its own, which saves neither the deal nor the organization). Bounded every way: only
# deals that moved recently, so switching the push on does not turn years of won deals
# into customers overnight; so many organizations a run, resuming where the last run
# stopped; and once a day, because every Acumatica push notification runs the sync.
SWEEP_WINDOW_DAYS = 30
SWEEP_LIMIT = 100
# organizations read per run; waiting ones with nothing new are passed over
SWEEP_PAGE = 500
SWEEP_EVERY = 20 * 3600
_SWEEP_RAN = f"{INFLIGHT_PREFIX}CustomerPushSweep::ran"
_SWEEP_CURSOR = f"{INFLIGHT_PREFIX}CustomerPushSweep::cursor"


def queue_pending_customer_pushes(settings=None, force: bool = False) -> int:
	"""Enqueue a push for unlinked organizations with a recently-moved deal in the
	trigger status; how many it queued. An organization whose push is waiting on a
	rep or a manager (an open Push Blocked / Possible Duplicate row) is skipped unless
	it, its address, the deal or the deal's primary contact changed since the row was
	written -- re-running it would only say the same thing again.

	Never raises: it runs inside the sync, and a retry that cannot be queued tonight is
	not a reason to fail the sync."""
	settings = settings or get_settings()
	if not _push_switched_on(settings):
		return 0
	cache = frappe.cache()
	if not force and cache.get_value(_SWEEP_RAN):
		return 0
	try:
		cursor = cache.get_value(_SWEEP_CURSOR) or ""
		rows = _pending_push_rows(settings, cursor)
		if not rows and cursor:
			cursor = ""
			rows = _pending_push_rows(settings, cursor)
		waiting = {}
		for issue in frappe.get_all(
			"CRM Acumatica Sync Issue",
			filters={
				"parent": "CRM Acumatica Settings",
				"entity": "Customer",
				"kind": ("in", list(WAITING_KINDS)),
				"dismissed": 0,
			},
			fields=["remote_id", "detected_on"],
		):
			seen = waiting.get(issue.remote_id)
			waiting[issue.remote_id] = max(seen, issue.detected_on) if seen else issue.detected_on

		queued = {}
		last = cursor
		for row in rows:
			if len(queued) >= SWEEP_LIMIT:
				break
			last = row.organization
			if row.organization in queued:
				continue
			since = waiting.get(row.organization)
			if since:
				changed = [
					t
					for t in (row.deal_modified, row.org_modified, row.address_modified, row.contact_modified)
					if t
				]
				if not changed or max(changed) <= since:
					continue
			queued[row.organization] = row.deal
		# a short page is the end of the list: the next run starts from the top again
		cache.set_value(
			_SWEEP_CURSOR,
			last if len(rows) >= SWEEP_PAGE or len(queued) >= SWEEP_LIMIT else "",
			expires_in_sec=INFLIGHT_TTL,
		)
		cache.set_value(_SWEEP_RAN, time.time(), expires_in_sec=SWEEP_EVERY)
		for organization, deal in queued.items():
			_enqueue_push(deal, organization)
		return len(queued)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Acumatica customer push sweep failed")
		return 0


def _pending_push_rows(settings, cursor: str) -> list:
	Deal = frappe.qb.DocType("CRM Deal")
	Org = frappe.qb.DocType("CRM Organization")
	Address = frappe.qb.DocType("Address")
	Link = frappe.qb.DocType("CRM Contacts")
	Contact = frappe.qb.DocType("Contact")
	return (
		frappe.qb.from_(Deal)
		.join(Org)
		.on(Org.name == Deal.organization)
		.left_join(Address)
		.on(Address.name == Org.address)
		.left_join(Link)
		.on((Link.parent == Deal.name) & (Link.parenttype == "CRM Deal") & (Link.is_primary == 1))
		.left_join(Contact)
		.on(Contact.name == Link.contact)
		# one row per organization: a customer with hundreds of won deals is one push
		.select(
			Max(Deal.name).as_("deal"),
			Deal.organization,
			Max(Deal.modified).as_("deal_modified"),
			Max(Org.modified).as_("org_modified"),
			Max(Address.modified).as_("address_modified"),
			Max(Contact.modified).as_("contact_modified"),
		)
		.where(
			(Deal.status == settings.deal_status)
			& (Deal.modified >= add_days(now_datetime(), -SWEEP_WINDOW_DAYS))
			& (Org.acumatica_id.isnull() | (Org.acumatica_id == ""))
			& (Org.acumatica_noteid.isnull() | (Org.acumatica_noteid == ""))
			& (Org.name > cursor)
		)
		.groupby(Deal.organization)
		.orderby(Deal.organization)
		.limit(SWEEP_PAGE)
	).run(as_dict=True)


def _issue(org_name: str, detail: str, kind: str = PUSH_FAILED, entity: str = "Customer") -> None:
	"""A push failure, one open row per record: the same outage on every deal save and
	every sync must not fill the capped table and push the real issues out of it."""
	upsert_sync_issue(entity, org_name, kind, detail)


def push_customer_for_deal(deal: str) -> None:
	"""Worker: does the actual Acumatica customer push. Re-loads the deal and
	re-checks the conditions, since time has passed since the hook enqueued this
	and the deal's status may have moved on.

	In order: the organization must not be linked already; it must carry what MBP
	keeps on a customer (_customer_facts -- no remote call before that); an earlier
	unanswered push is looked for; it must not look like a customer Acumatica already
	has, by the synced organizations here and then by Acumatica itself -- unless a
	manager confirmed it new and it is still what they confirmed; then the PUT, and
	after it the salesperson and the primary contact."""
	doc = frappe.get_doc("CRM Deal", deal)
	settings = get_settings()
	if (
		not settings.enabled
		or not settings.create_customer_on_status_change
		or doc.status != settings.deal_status
		or not doc.organization
	):
		return

	org = frappe.get_doc("CRM Organization", doc.organization)
	if org.get("acumatica_noteid") or org.get("acumatica_id"):
		# Already linked -- record the link on the deal and stop. Either identity
		# counts: the spreadsheet import gives every organization its real
		# CustomerID (acumatica_id) but no NoteID, because the exports carry none.
		# Testing NoteID alone treated all 1,091 imported organizations as unknown
		# and would have PUT a duplicate customer into the client's live ERP the
		# first time a rep won one of their deals -- and then overwritten the real
		# CustomerID with the duplicate's. create_sales_quote_from_deal already
		# accepts acumatica_id as sufficient linkage; the push follows the same rule.
		if not doc.get("acumatica_customer") and org.get("acumatica_id"):
			frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", org.get("acumatica_id"))
		if org.get("acumatica_id") and frappe.cache().get_value(_contact_followup_key(org.name)):
			# the customer is ours, but setting its primary contact failed last time
			_push_primary_contact(AcumaticaClient(settings), org.name, org.acumatica_id)
		return

	facts = _customer_facts(doc, org, settings)
	if facts.missing:
		missing = ", ".join(facts.missing)
		_report(
			org.name,
			doc,
			PUSH_BLOCKED,
			f"not created in Acumatica: missing {missing}",
			_("Add {0} so {1} can be created as a customer in Acumatica.").format(
				missing, frappe.utils.escape_html(org.organization_name or org.name)
			),
		)
		return
	# past the gate: whatever it was blocked on is fixed
	dismiss_sync_issues("Customer", org.name, (PUSH_BLOCKED,))

	client = AcumaticaClient(settings)
	payload = _customer_payload(facts, settings)

	inflight = _inflight_key("Customer", org.name)
	started_with = frappe.cache().get_value(inflight, use_local_cache=False)
	marker = _read_marker(started_with)
	if marker:
		# An earlier push never heard back, and the next deal save fired this one. Under
		# AutoNumber a second PUT is a second customer; under From Organization Name the
		# collision check below would refuse the id the first one took. Link what it
		# made instead -- but only what it can only have made, looked for by what it
		# SENT: the organization may have been renamed since.
		try:
			earlier, why_not = _earlier_customer(client, payload, marker)
		except (AcumaticaError, requests.RequestException, ValueError) as e:
			_issue(
				org.name,
				f"could not look for the customer an unanswered push may have created: {e} :: {_reason(e)}",
			)
			return
		if why_not:
			# the marker stays: nothing is sent until somebody links the right one
			_issue(org.name, why_not)
			return
		if earlier:
			_link_customer(org.name, doc.name, earlier)
			_settle_inflight(inflight)
			_commit()
			_after_customer_created(client, org.name, v(earlier, "CustomerID"), facts.contact, doc, settings)
			return

	# Decided without a lock: the reads below go to Acumatica, and a row lock held
	# across them would stall a rep's save of the organization, or a manager's
	# action, for as long as Acumatica takes. What the decision rests on -- the link
	# and the confirmation -- is re-read under the lock just before the PUT.
	confirmation = org.get("acumatica_confirmed_for") or ""
	confirmed_past = _confirmed_past(confirmation, facts)

	candidates = [c for c in _local_duplicates(org, facts) if c["customer_id"] not in confirmed_past]
	if candidates:
		_report_duplicate(org, doc, candidates)
		return

	if payload.get("CustomerID"):
		collision = _customer_id_collision(client, payload["CustomerID"], org.name)
		if collision:
			_issue(org.name, collision)
			return

	try:
		# right before the PUT: a customer keyed in at Acumatica since the last sync is
		# in no organization here yet. The same-name customers that exist now are also
		# what an unanswered PUT must never be taken for.
		preexisting, candidates = _remote_duplicates(client, facts)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		# same rule as the collision check: "the check failed" is not "there is none"
		_issue(org.name, f"could not check Acumatica for an existing customer: {e} :: {_reason(e)}")
		return
	candidates = [c for c in candidates if c["customer_id"] not in confirmed_past]
	if candidates:
		_report_duplicate(org, doc, candidates)
		return

	# enqueue_after_commit only defers the ENQUEUE into frappe.db.after_commit -- a plain
	# deque with no de-duplication of its own. Two deals on the same organization saved
	# inside one request both pass queue_customer_push's redis dedup check at hook time
	# (nothing has committed yet, so neither looks like a duplicate to the other) and
	# both land a job at commit; two workers then reach this point concurrently, and the
	# unlocked read above can't see a link a concurrent winner is mid-write on. Re-read
	# with a row lock immediately before the PUT: the loser blocks here until the
	# winner's write below commits, then sees the link already populated and no-ops
	# instead of PUTting a second Customer into the client's ERP. A confirmation that
	# changed since the decision above ends this run too: the job confirm_new_customer
	# queued decides on it.
	locked = frappe.db.get_value(
		"CRM Organization",
		org.name,
		["acumatica_noteid", "acumatica_id", "acumatica_confirmed_for"],
		as_dict=True,
		for_update=True,
	)
	if locked and (locked.acumatica_noteid or locked.acumatica_id):
		if not doc.get("acumatica_customer") and locked.acumatica_id:
			frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", locked.acumatica_id)
		return
	if locked and (locked.get("acumatica_confirmed_for") or "") != confirmation:
		return
	current = frappe.cache().get_value(inflight, use_local_cache=False)
	if current and current != started_with:
		# Another job for this organization took the lock first and sent its PUT, which
		# got no answer: the customer may exist. Sending ours too would make a second;
		# the next push recovers what that one made.
		return

	_mark_inflight(
		inflight,
		{
			"sent_at": time.time(),
			"preexisting": preexisting,
			# what was sent, so recovery after a rename looks for the right thing
			"name": payload["CustomerName"],
			"customer_id": payload.get("CustomerID"),
		},
	)
	try:
		created = client.put("Customer", payload)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		# This runs in a background job, off the user's deal save -- but a raised
		# exception here still fails silently from their point of view, so a DNS
		# blip, a read timeout or an HTML error page from a proxy (json() raises
		# ValueError/JSONDecodeError) must land in the sync-issues table like any
		# other push failure rather than just dying in the worker log.
		detail = f"{e} :: {_reason(e)}"
		if _outcome_unknown(e):
			# the marker stays: the customer may exist, and the next push looks first
			detail = f"{detail} -- Acumatica may have created the customer anyway; the next push looks for it before sending another"
		else:
			frappe.cache().delete_value(inflight)
		_issue(org.name, detail)
		return

	_link_customer(org.name, doc.name, created)
	_settle_inflight(inflight)
	_commit()
	_after_customer_created(client, org.name, v(created, "CustomerID"), facts.contact, doc, settings)


def _link_customer(org_name: str, deal_name: str, customer) -> None:
	frappe.db.set_value(
		"CRM Organization",
		org_name,
		{"acumatica_noteid": v(customer, "NoteID"), "acumatica_id": v(customer, "CustomerID")},
	)
	frappe.db.set_value("CRM Deal", deal_name, "acumatica_customer", v(customer, "CustomerID"))


def _read_marker(raw) -> dict | None:
	"""An in-flight marker as ``{"sent_at", "preexisting"}``. A bare timestamp is a
	marker written before the push recorded which same-name customers already
	existed: ``preexisting`` None, which makes any same-name hit ambiguous."""
	if not raw:
		return None
	if isinstance(raw, dict):
		return raw
	try:
		return {"sent_at": float(raw), "preexisting": None}
	except (TypeError, ValueError):
		return {"sent_at": None, "preexisting": None}


def confirmation_value(facts, candidates) -> str:
	"""What confirm_new_customer stores: the fingerprint of what the manager saw, and
	the customer codes they confirmed it is not."""
	return json.dumps(
		{"hash": confirmation_hash(facts), "past": sorted({c for c in candidates if c})}, sort_keys=True
	)


def _confirmed_past(raw: str, facts) -> set:
	"""The customer codes a manager confirmed this organization is not -- empty when
	there is no confirmation, or it no longer matches what the push is about to send.
	A candidate outside the set still blocks: the manager never saw it."""
	if not raw:
		return set()
	try:
		data = json.loads(raw)
	except ValueError:
		return set()
	if not isinstance(data, dict) or data.get("hash") != confirmation_hash(facts):
		return set()
	return {str(c) for c in data.get("past") or []}


def move_markers_on_rename(doc, method, old: str, new: str, merge: bool = False) -> None:
	"""CRM Organization after_rename: the in-flight markers are keyed by the docname,
	and one orphaned by a rename is a push that forgot it may already have created the
	customer -- the next one sends a second."""
	cache = frappe.cache()
	for entity in ("Customer", "CustomerContact"):
		value = cache.get_value(_inflight_key(entity, old))
		if not value:
			continue
		if not cache.get_value(_inflight_key(entity, new)):
			cache.set_value(_inflight_key(entity, new), value, expires_in_sec=INFLIGHT_TTL)
		cache.delete_value(_inflight_key(entity, old))


def confirmation_hash(facts) -> str:
	"""What a manager confirmed as a new customer: the normalised name, the VAT
	number's digits and the primary contact's email. Any of them changing afterwards
	(a rename onto an existing customer) puts the organization back through the
	duplicate checks."""
	email = _clean(facts.contact.email_id).lower() if facts.contact else ""
	basis = "|".join((normalise_name(facts.name), normalise_vat(facts.vat), email))
	return hashlib.sha256(basis.encode()).hexdigest()[:40]


# --- what a customer needs before it is created ------------------------------------

MAX_CANDIDATES = 5
SAME_VAT = "same VAT number"

_ADDRESS_FIELDS = ["address_line1", "address_line2", "city", "state", "pincode", "country"]
_CONTACT_FIELDS = [
	"name",
	"first_name",
	"last_name",
	"email_id",
	"mobile_no",
	"phone",
	"designation",
	"acumatica_id",
]


def _primary_contact_name(deal_doc) -> str | None:
	"""The deal's primary contact; a deal with a single contact has that one."""
	rows = [row for row in (deal_doc.get("contacts") or []) if row.contact]
	primary = next((row for row in rows if row.is_primary), None)
	if not primary and len(rows) == 1:
		primary = rows[0]
	return primary.contact if primary else None


def _clean(value) -> str:
	return (value or "").strip() if isinstance(value, str) else ("" if value is None else str(value))


def _customer_facts(deal_doc, org, settings) -> frappe._dict:
	"""Everything the customer is built from, and ``missing`` -- what MBP's customers
	all carry that this one does not. Local reads only: nothing goes to Acumatica for
	a customer that would be created incomplete."""
	missing = []
	name = _clean(org.organization_name)
	if not name:
		missing.append(_("the organization name"))

	address = None
	if org.get("address"):
		address = frappe.db.get_value("Address", org.address, _ADDRESS_FIELDS, as_dict=True)
	country_code = None
	if not address:
		missing.append(_("an address on the organization"))
	else:
		if not _clean(address.address_line1):
			missing.append(_("address line 1"))
		if not _clean(address.city):
			missing.append(_("the city"))
		if address.country:
			country_code = _clean(frappe.db.get_value("Country", address.country, "code")).upper() or None
		if not country_code:
			missing.append(_("the country"))

	contact = None
	contact_name = _primary_contact_name(deal_doc)
	if contact_name:
		contact = frappe.db.get_value("Contact", contact_name, _CONTACT_FIELDS, as_dict=True)
	if not contact:
		missing.append(_("a primary contact on the deal"))
	else:
		if not _clean(contact.first_name):
			missing.append(_("the primary contact's first name"))
		if not (_clean(contact.email_id) or _clean(contact.phone) or _clean(contact.mobile_no)):
			missing.append(_("the primary contact's email or phone"))

	if not _clean(settings.get("new_customer_class")):
		missing.append(_("a customer class in the Acumatica settings"))

	return frappe._dict(
		missing=missing,
		name=name,
		address=address,
		country_code=country_code,
		contact=contact,
		vat=_clean(org.get("tax_registration_id")),
		website=_clean(org.get("website")),
		currency=org.get("currency"),
	)


def _compact(values: dict) -> dict:
	"""Leave out what has no value: an empty field in a PUT is an instruction to clear."""
	return {k: val for k, val in values.items() if val not in (None, "", [], {})}


def _tax_zone(country: str | None, settings) -> str | None:
	home = settings.get("home_country") or "South Africa"
	zone = settings.get("tax_zone_home") if country == home else settings.get("tax_zone_abroad")
	return _clean(zone) or None


def _salesperson(deal_doc, settings) -> str | None:
	"""The deal owner's Acumatica salesperson code, when exactly one maps to them."""
	from crm.integrations.acumatica.quotes import parse_owner_map  # quotes imports this module

	owner = deal_doc.get("deal_owner")
	if not owner:
		return None
	try:
		owners = parse_owner_map(settings.get("salesperson_owners"))
	except ValueError:
		# the sweep reports a broken map; a customer without a salesperson is still one
		return None
	codes = [code for code, user in owners.items() if user == owner]
	return codes[0] if len(codes) == 1 else None


def _customer_payload(facts, settings) -> dict:
	"""The Customer PUT as MBP keeps its customers. Terms, credit limit, status and
	statement cycle are the customer class's and the accounts department's to set,
	and are never sent."""
	address = facts.address
	contact = facts.contact
	payload = _compact(
		{
			"CustomerName": facts.name,
			"CustomerClass": _clean(settings.get("new_customer_class")),
			"CurrencyID": facts.currency or frappe.db.get_single_value("FCRM Settings", "currency"),
			"TaxZone": _tax_zone(address.country, settings),
			"TaxRegistrationID": facts.vat,
		}
	)
	main_address = _compact(
		{
			"AddressLine1": _clean(address.address_line1),
			"AddressLine2": _clean(address.address_line2),
			"City": _clean(address.city),
			"State": state_code(address.state, facts.country_code),
			"PostalCode": _clean(address.pincode),
			"Country": facts.country_code,
		}
	)
	main_contact = _compact(
		{
			"Email": _clean(contact.email_id),
			"Phone1": _clean(contact.phone) or _clean(contact.mobile_no),
			"WebSite": facts.website,
		}
	)
	# client.put wraps only the top level and passes a dict through as a nested entity
	# already in Acumatica's {"value": x} form, so the nested ones are wrapped here
	main_contact["Address"] = wrap(main_address)
	payload["MainContact"] = wrap(main_contact)
	if settings.customer_numbering == "From Organization Name":
		# Acumatica's default CUSTOMER ID segment is 10; the setting exists for
		# tenants that widened it.
		limit = int(settings.get("customer_id_max_length") or 10)
		payload["CustomerID"] = re.sub(r"[^A-Z0-9]", "", facts.name.upper())[:limit]
	return payload


# --- duplicates ---------------------------------------------------------------------


def _add_candidate(found: dict, customer_id, organization, organization_name, reason) -> None:
	if not customer_id:
		return
	entry = found.setdefault(
		customer_id,
		{
			"customer_id": customer_id,
			"organization": organization,
			"organization_name": organization_name,
			"reasons": [],
		},
	)
	entry["organization"] = entry["organization"] or organization
	if reason not in entry["reasons"]:
		entry["reasons"].append(reason)


_REASON_ORDER = (SAME_VAT, "same name", "same contact email", "similar name")


def _ranked(found: dict) -> list[dict]:
	"""Strongest evidence first, then by customer code -- deterministic, so the same
	candidates make the same issue row and the open-issue check sees a repeat."""

	def rank(entry):
		best = min(_REASON_ORDER.index(r) if r in _REASON_ORDER else 99 for r in entry["reasons"])
		return (best, entry["customer_id"])

	return sorted(found.values(), key=rank)[:MAX_CANDIDATES]


def _local_duplicates(org, facts) -> list[dict]:
	"""Synced customers this organization may already be. Every Acumatica customer is
	an organization here with its code, so one read of those (~1,100 rows on MBP's
	tenant) is the whole comparison; no per-row queries. Not called once a manager
	confirmed the organization as new (and it still matches what they confirmed)."""
	vat = normalise_vat(facts.vat)
	linked = frappe.get_all(
		"CRM Organization",
		filters={"acumatica_id": ("is", "set"), "name": ("!=", org.name)},
		fields=["name", "organization_name", "acumatica_id", "tax_registration_id"],
		limit=20000,
	)
	found = {}
	ours = normalise_name(facts.name)
	for row in linked:
		if vat and normalise_vat(row.tax_registration_id) == vat:
			_add_candidate(found, row.acumatica_id, row.name, row.organization_name, SAME_VAT)
		reason = name_match(ours, normalise_name(row.organization_name))
		if reason:
			_add_candidate(found, row.acumatica_id, row.name, row.organization_name, reason)

	email = _clean(facts.contact.email_id).lower() if facts.contact else ""
	if email:
		by_name = {row.name: row for row in linked}
		Email = frappe.qb.DocType("Contact Email")
		Contact = frappe.qb.DocType("Contact")
		companies = (
			frappe.qb.from_(Email)
			.join(Contact)
			.on(Contact.name == Email.parent)
			.select(Contact.company_name)
			.distinct()
			.where(
				(Email.parenttype == "Contact")
				& (Email.email_id == email)
				& Contact.company_name.isnotnull()
				& (Contact.company_name != org.name)
			)
			.limit(50)
		).run(pluck=True)
		for company in companies:
			row = by_name.get(company)
			if row:
				_add_candidate(found, row.acumatica_id, row.name, row.organization_name, "same contact email")
	return _ranked(found)


def _vat_forms(vat: str) -> list[str]:
	"""The VAT number as typed and as digits: Acumatica holds whichever someone keyed."""
	raw = _clean(vat)
	digits = normalise_vat(raw)
	if not digits:
		return []
	return [raw] if raw == digits else [raw, digits]


def _remote_duplicates(client, facts) -> tuple[list[str], list[dict]]:
	"""(the CustomerIDs Acumatica already has by this exact name, candidates by name or
	VAT number) -- the customers created there since the last sync. Separate reads
	rather than one `or` filter: each is a shape this integration already relies on."""
	queries = [("same name", f"CustomerName eq {_odata(facts.name)}")]
	queries += [(SAME_VAT, f"TaxRegistrationID eq {_odata(form)}") for form in _vat_forms(facts.vat)]
	found = {}
	same_name = []
	for reason, filter_ in queries:
		page = client.get_page(
			"Customer",
			top=RECOVERY_PAGE if reason == "same name" else MAX_CANDIDATES,
			filter=filter_,
			select="CustomerID,CustomerName",
			orderby=None,
		)
		for rec in page or []:
			customer_id = v(rec, "CustomerID")
			if reason == "same name" and customer_id:
				same_name.append(customer_id)
			holder = frappe.db.get_value("CRM Organization", {"acumatica_id": customer_id}, "name")
			_add_candidate(found, customer_id, holder, v(rec, "CustomerName"), reason)
	return same_name, _ranked(found)


def _describe(candidates: list[dict]) -> str:
	return "; ".join(
		f"{c['organization_name'] or c['organization'] or '?'} [{c['customer_id']}] ({', '.join(c['reasons'])})"
		for c in candidates
	)


def _report_duplicate(org, deal_doc, candidates: list[dict]) -> None:
	described = _describe(candidates)
	_report(
		org.name,
		deal_doc,
		POSSIBLE_DUPLICATE,
		f"not created in Acumatica: may already be {described}. "
		"A manager must link it to that customer (or move the deal to the organization that "
		"already holds it) or confirm it is new.",
		# Not the candidates: they may be another rep's customers, which this rep is not
		# allowed to see. The manager's panel names them.
		_(
			"{0} may already be a customer in Acumatica. A sales manager is reviewing it before it is created."
		).format(frappe.utils.escape_html(org.organization_name or org.name)),
		candidates,
	)


def _report(org_name: str, deal_doc, kind: str, detail: str, message: str, candidates=None) -> None:
	"""A waiting push: one open row per organization and kind, brought up to date when
	it is already there, and one in-app note to the deal owner when the row is new.
	Every deal save and every sync re-runs the push, and the rep was told the first
	time. Moving on from one kind to the other (blocked to duplicate, or back) clears
	the stale one."""
	dismiss_sync_issues("Customer", org_name, tuple(k for k in WAITING_KINDS if k != kind))
	if upsert_sync_issue("Customer", org_name, kind, detail, candidates):
		_notify_owner(deal_doc, message)


def _notify_owner(deal_doc, message: str) -> None:
	owner = deal_doc.get("deal_owner")
	if not owner or owner in ("Administrator", "Guest"):
		return
	try:
		from crm.fcrm.doctype.crm_notification.crm_notification import notify_user

		notify_user(
			{
				# the system's note, not whoever's save woke the job (notify_user also
				# drops a note whose sender is its recipient)
				"owner": "Administrator",
				"assigned_to": owner,
				"notification_type": "Assignment",
				"message": message,
				"notification_text": f'<div class="mb-2 leading-5 text-ink-gray-5">{message}</div>',
				"reference_doctype": "CRM Deal",
				"reference_docname": deal_doc.name,
				"redirect_to_doctype": "CRM Deal",
				"redirect_to_docname": deal_doc.name,
			}
		)
	except Exception:
		# the sync issue is the record; a note that could not be written must not undo it
		frappe.log_error(frappe.get_traceback(), "Acumatica customer push notification failed")


# --- after the customer exists ------------------------------------------------------


def _contact_followup_key(org_name: str) -> str:
	# under the in-flight prefix so frappe.clear_cache() keeps it (hooks.persistent_cache_keys)
	return _inflight_key("CustomerContact", org_name)


def _after_customer_created(client, org_name: str, customer_id, contact, deal_doc, settings) -> None:
	"""The customer is linked and committed: clear the issues that held it back, then
	give it its salesperson and its primary contact. Nothing from here on rolls the
	customer back or makes it again -- a failure is a sync issue, and the next save of
	the deal tries the contact again."""
	try:
		dismiss_sync_issues("Customer", org_name, (*WAITING_KINDS, PUSH_FAILED))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Acumatica sync issue dismissal failed")
	if not customer_id:
		return
	_push_salesperson(client, org_name, customer_id, deal_doc, settings)
	if not contact or contact.get("acumatica_id"):
		# a contact already linked is somebody's in Acumatica; it is not ours to re-home
		return
	frappe.cache().set_value(_contact_followup_key(org_name), contact.name, expires_in_sec=INFLIGHT_TTL)
	_push_primary_contact(client, org_name, customer_id)


def _push_salesperson(client, org_name: str, customer_id: str, deal_doc, settings) -> None:
	"""A second PUT rather than part of the first: a new customer has no MAIN location
	yet, and a Salespersons row without a LocationID can be refused -- which in the
	create PUT would have refused the customer itself."""
	salesperson = _salesperson(deal_doc, settings)
	if not salesperson:
		return
	try:
		client.put(
			"Customer",
			{"CustomerID": customer_id, "Salespersons": [{"SalespersonID": salesperson, "Default": True}]},
		)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		_issue(
			org_name,
			f"customer {customer_id} was created, but salesperson {salesperson} was not set on it: "
			f"{e} :: {_reason(e)} -- set it in Acumatica",
			entity="Customer Salesperson",
		)


def _push_primary_contact(client, org_name: str, customer_id: str) -> None:
	"""PUT the primary contact under the new customer and make it the customer's
	primary contact. Idempotent: the contact is looked for under the customer before
	one is created, and a contact already linked here is only re-pointed."""
	key = _contact_followup_key(org_name)
	contact_name = frappe.cache().get_value(key)
	contact = (
		frappe.db.get_value("Contact", contact_name, _CONTACT_FIELDS, as_dict=True) if contact_name else None
	)
	if not contact:
		frappe.cache().delete_value(key)
		return
	try:
		contact_id = contact.acumatica_id
		if not contact_id:
			rec = _existing_remote_contact(client, customer_id, contact)
			if not rec:
				rec = client.put(
					"Contact",
					_compact(
						{
							"FirstName": _clean(contact.first_name),
							"LastName": _clean(contact.last_name),
							"Email": _clean(contact.email_id),
							"Phone1": _clean(contact.phone) or _clean(contact.mobile_no),
							"JobTitle": _clean(contact.designation),
							"BusinessAccount": customer_id,
						}
					),
				)
			contact_id = v(rec, "ContactID")
			if contact_id in (None, ""):
				raise ValueError("Acumatica answered the contact without a ContactID")
			# linked before the next PUT, so a retry after it fails re-points, not re-creates
			frappe.db.set_value(
				"Contact",
				contact.name,
				{"acumatica_id": str(contact_id), "acumatica_noteid": v(rec, "NoteID")},
			)
		client.put("Customer", {"CustomerID": customer_id, "PrimaryContactID": int(contact_id)})
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		_issue(
			contact.name,
			f"customer {customer_id} was created, but its primary contact was not set: {e} :: {_reason(e)}"
			" -- the next save of the deal tries again",
			entity="Contact",
		)
		return
	dismiss_sync_issues("Contact", contact.name, (PUSH_FAILED,))
	_settle_inflight(key)


def _existing_remote_contact(client, customer_id: str, contact):
	"""The contact under ``customer_id`` an earlier attempt already made, or None:
	by email when there is one, else by name."""
	filter_ = f"BusinessAccount eq {_odata(customer_id)}"
	email = _clean(contact.email_id)
	if email:
		filter_ += f" and Email eq {_odata(email)}"
	else:
		filter_ += f" and FirstName eq {_odata(_clean(contact.first_name))}"
		if _clean(contact.last_name):
			filter_ += f" and LastName eq {_odata(_clean(contact.last_name))}"
	page = client.get_page("Contact", top=1, filter=filter_, select="ContactID,NoteID", orderby=None)
	return page[0] if page else None


RECOVERY_PAGE = 10


def _earlier_customer(client, payload: dict, marker: dict):
	"""(the customer an unanswered push made, or None; why none may be adopted, or None).

	Under From Organization Name the push carried an id that was checked free just
	before it was sent, so a customer with that id now is the push's own. Under
	AutoNumber there is only the name, and a same-name customer may well be somebody
	else's -- most of all after a manager confirmed the organization as new beside an
	existing namesake. So the customers the push saw by that name before it sent are
	excluded, as is any customer an organization here already holds; exactly one left
	is the push's, none means it made nothing, and more than one is not a guess to
	make on the client's ERP."""
	# what the unanswered push sent; a marker from before it was recorded, the payload
	sent_name = marker.get("name") or payload["CustomerName"]
	sent_id = marker.get("customer_id") if "name" in marker else payload.get("CustomerID")
	if sent_id:
		page = client.get_page("Customer", top=2, filter=f"CustomerID eq {_odata(sent_id)}", orderby=None)
		if not page:
			return None, None
		if _held_here(v(page[0], "CustomerID")):
			return None, (
				f"customer {v(page[0], 'CustomerID')} the unanswered push may have made is already "
				"linked to another organization here; link the right one by hand"
			)
		return page[0], None

	page = client.get_page(
		"Customer",
		top=RECOVERY_PAGE,
		filter=f"CustomerName eq {_odata(sent_name)}",
		orderby=None,
	)
	if not page:
		return None, None
	preexisting = marker.get("preexisting")
	if preexisting is None:
		return None, (
			f"Acumatica has a customer named {sent_name}, and an unanswered push "
			"recorded no list to tell its own from an existing one; link the right one by hand"
		)
	fresh = [
		rec
		for rec in page
		if v(rec, "CustomerID")
		and v(rec, "CustomerID") not in preexisting
		and not _held_here(v(rec, "CustomerID"))
	]
	if not fresh:
		return None, None
	if len(fresh) > 1:
		return None, (
			f"Acumatica has more than one new customer named {sent_name} "
			f"({', '.join(v(r, 'CustomerID') for r in fresh)}); link the right one by hand"
		)
	return fresh[0], None


def _held_here(customer_id) -> bool:
	return bool(frappe.db.exists("CRM Organization", {"acumatica_id": customer_id}))


def _reason(e) -> str:
	return e.detail() if isinstance(e, AcumaticaError) else str(e)


def _customer_id_collision(client, customer_id: str, org_name: str) -> str | None:
	"""Why ``customer_id`` must not be PUT for ``org_name`` -- or None when it is free.

	Acumatica's Customer PUT is an upsert keyed on CustomerID, and in "From
	Organization Name" mode that key is the name stripped to alphanumerics and
	truncated to the CUSTOMER ID segment: "Acme Industries" and "Acme Industrial
	Ltd" both derive ACMEINDUST. Sending the second would RENAME the first
	customer in the client's ERP and leave two CRM organizations pointing at one
	record -- silent, and not undoable from here. A taken id is refused instead,
	and the sync issue tells an admin to widen the segment or set the id by hand.

	A read that cannot answer counts as taken too: the point is never to PUT over
	somebody else's customer, and "the check failed" is not "the id is free".
	"""
	holder = frappe.db.get_value(
		"CRM Organization", {"acumatica_id": customer_id, "name": ("!=", org_name)}, "name"
	)
	if holder:
		return f"CustomerID {customer_id} derived from the name is already held by CRM Organization {holder}"
	try:
		taken = _remote_customer_exists(client, customer_id)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		return f"could not check whether CustomerID {customer_id} is free: {e} :: {_reason(e)}"
	if taken:
		return f"CustomerID {customer_id} derived from the name already exists in Acumatica"
	return None


def _remote_customer_exists(client, customer_id: str) -> bool:
	"""A filtered read rather than GET Customer/<id>: Acumatica answers a missing key
	with a 500 "No entity satisfies the condition" on some versions and a 404 on
	others, while an empty filtered page means "not found" on all of them. The id is
	alphanumeric by construction (the regex above strips everything else), so it
	needs no OData quoting."""
	page = client.get_page("Customer", top=1, filter=f"CustomerID eq '{customer_id}'", select="CustomerID")
	return bool(page)


# POST only. Frappe checks CSRF on unsafe methods alone and rolls a GET's writes back:
# a pasted link or an <img> on any page a rep opened would PUT an order into the
# client's ERP on every visit, and the rollback threw away the OrderNbr that stops
# the next one.
@frappe.whitelist(methods=["POST"])
def create_sales_quote_from_deal(crm_deal: str) -> str:
	frappe.has_permission("CRM Deal", "write", doc=crm_deal, throw=True)
	settings = get_settings()
	if not settings.enabled:
		frappe.throw(_("The Acumatica integration is not enabled"))

	deal = frappe.get_doc("CRM Deal", crm_deal)
	existing_quote = deal.get("acumatica_sales_quote")
	if existing_quote:
		# SalesOrder is a PUT-upsert with no key in the body, so every click would create
		# ANOTHER order in the client's ERP. The stored OrderNbr is the idempotency key.
		frappe.throw(_("Sales quote {0} already exists in Acumatica").format(existing_quote))

	customer_id = deal.get("acumatica_customer") or frappe.db.get_value(
		"CRM Organization", deal.organization, "acumatica_id"
	)
	if not customer_id:
		frappe.throw(_("This deal's organization is not linked to an Acumatica customer yet"))

	products = deal.get("products") or []
	details = []
	unlinked = []
	# CRM Deal's child table is `products` (CRM Products rows); the row's link to
	# the CRM Product is `product_code`, the quantity field is `qty`.
	for row in products:
		# a line typed in by name has no product_code, and so no inventory item either
		inventory_id = (
			frappe.db.get_value("CRM Product", row.product_code, "acumatica_id") if row.product_code else None
		)
		if not inventory_id:
			# A quote missing one of its lines still saves and still shows a success
			# toast -- the rep has no reason to notice it shipped short. Refuse the
			# whole thing instead of sending a partial order. Name a free-text line by
			# what the rep typed: a None in the list crashed the join below.
			unlinked.append(row.product_code or row.product_name or _("a line with no product"))
			continue
		line = {
			"InventoryID": inventory_id,
			"OrderQty": row.qty or 1,
			"UnitPrice": row.rate,
			"DiscountPercent": row.discount_percentage,
		}
		# Acumatica reprices any line whose price keys are absent; send what the deal
		# negotiated, and only the keys the row actually carries.
		details.append({key: value for key, value in line.items() if value is not None})

	if unlinked:
		frappe.throw(
			_(
				"These products are not linked to Acumatica inventory items: {0}. "
				"Run a backfill or link them, then try again."
			).format(", ".join(unlinked))
		)

	# Acumatica books a quote in its customer's currency and reads every UnitPrice in
	# it. A deal priced in another currency would reach a USD customer as ZAR figures
	# taken for dollars -- about eighteen times the price, and nothing flags it.
	base_currency = frappe.db.get_single_value("FCRM Settings", "currency")
	deal_currency = deal.get("currency") or base_currency
	customer_currency = (
		frappe.db.get_value("CRM Organization", deal.organization, "currency") or base_currency
	)
	if deal_currency != customer_currency:
		frappe.throw(
			_(
				"This deal is priced in {0}, but its customer is billed in {1} in Acumatica. "
				"Change the deal's currency to {1} and its prices with it, then try again."
			).format(deal_currency, customer_currency)
		)

	payload = {
		"OrderType": settings.quote_order_type,
		"CustomerID": customer_id,
		"Description": _quote_description(deal.name),
	}
	if deal_currency:
		# said outright rather than left to the customer's default, so a currency the
		# CRM has out of date is refused or honoured by Acumatica, never misread
		payload["CurrencyID"] = deal_currency
	if details:
		payload["Details"] = details

	# The check above read the deal without a lock. Two quick clicks are two requests
	# that both pass it before either has an OrderNbr to store, and SalesOrder is a
	# PUT with no key in the body -- so the second creates a second order in the
	# client's ERP. Re-read under a row lock right before the PUT: the second request
	# blocks here until the first commits, then sees its OrderNbr and refuses.
	locked_quote = frappe.db.get_value("CRM Deal", deal.name, "acumatica_sales_quote", for_update=True)
	if locked_quote:
		frappe.throw(_("Sales quote {0} already exists in Acumatica").format(locked_quote))

	client = AcumaticaClient(settings)
	inflight = _inflight_key("SalesOrder", deal.name)
	sent_at = frappe.cache().get_value(inflight)
	if sent_at:
		# An earlier attempt never heard back -- a timeout, or the proxy giving up on
		# the request first. Adopt the order it made rather than PUT a second one.
		try:
			earlier = _earlier_quote(client, payload)
		except (AcumaticaError, requests.RequestException, ValueError) as e:
			frappe.throw(
				_(
					"An earlier attempt to create this quote got no answer from Acumatica, and "
					"looking for it failed: {0}. Try again in a few minutes."
				).format(_reason(e))
			)
		if earlier:
			frappe.db.set_value("CRM Deal", deal.name, "acumatica_sales_quote", earlier)
			_settle_inflight(inflight)
			return earlier
		if time.time() - float(sent_at) < QUOTE_SETTLE_SECONDS:
			frappe.throw(
				_(
					"An earlier attempt to create this quote got no answer from Acumatica, which "
					"may still be creating it. Try again in a few minutes."
				)
			)

	_mark_inflight(inflight)
	try:
		created = client.put("SalesOrder", payload, timeout=_quote_write_timeout())
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		if not _outcome_unknown(e):
			frappe.cache().delete_value(inflight)
			# The status line alone ("PUT ... -> 422") tells a rep nothing; the reason
			# Acumatica gave is in the body.
			frappe.throw(_("Acumatica refused the sales quote: {0}").format(_reason(e)))
		# Not "it failed": the order may well exist. The marker stays, so the retry
		# this invites adopts it instead of making a second one.
		frappe.throw(
			_(
				"No answer came back from Acumatica ({0}). The quote may still have been created — "
				"try again in a few minutes and Vectora will pick it up rather than create another."
			).format(_reason(e))
		)
	order_nbr = v(created, "OrderNbr") or ""
	if order_nbr:
		frappe.db.set_value("CRM Deal", deal.name, "acumatica_sales_quote", order_nbr)
		_settle_inflight(inflight)
	return order_nbr


# Also how the sync's new-quote pass (quotes.py) recognises a quote this CRM made.
QUOTE_DESCRIPTION_PREFIX = "Vectora deal "


def _quote_description(deal_name: str) -> str:
	# also the key _earlier_quote finds an unanswered attempt's order by
	return f"{QUOTE_DESCRIPTION_PREFIX}{deal_name}"


def _earlier_quote(client, payload: dict) -> str | None:
	"""The OrderNbr of the quote an unanswered attempt made for this deal, or None."""
	filter_ = (
		f"OrderType eq {_odata(payload['OrderType'])}"
		f" and CustomerID eq {_odata(payload['CustomerID'])}"
		f" and Description eq {_odata(payload['Description'])}"
	)
	page = client.get_page("SalesOrder", top=1, filter=filter_, select="OrderNbr", orderby=None)
	return v(page[0], "OrderNbr") if page else None


def _quote_write_timeout() -> int:
	"""How long the quote PUT may wait. It runs inside the rep's request, behind a proxy
	that gives up at PROXY_READ_TIMEOUT (120s on the shipped stack): at the client's
	WRITE_TIMEOUT of 120 the proxy answered first, and the rep got a bare gateway error
	instead of the warning below. The token fetch and the lookups come out of the same
	budget, so they are kept back from it."""
	proxy = cint(frappe.conf.get("crm_proxy_read_timeout")) or DEFAULT_PROXY_READ_TIMEOUT
	return max(proxy - TIMEOUT - 15, 15)
