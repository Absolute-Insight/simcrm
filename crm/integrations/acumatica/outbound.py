import re
import time

import frappe
import requests
from frappe import _
from frappe.utils import cint

from crm.agent.doctype.crm_agent_settings.crm_agent_settings import DEFAULT_PROXY_READ_TIMEOUT
from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_settings,
	record_sync_issue,
)
from crm.integrations.acumatica.client import TIMEOUT, AcumaticaClient, AcumaticaError, v

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


def _mark_inflight(key: str) -> None:
	frappe.cache().set_value(key, time.time(), expires_in_sec=INFLIGHT_TTL)


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


def queue_customer_push(doc, method):
	"""CRM Deal on_update handler. Mirrors the ERPNext integration's trigger shape:
	fires once when the deal reaches the configured status. Cheap checks only --
	the HTTP PUT itself runs off-thread in push_customer_for_deal so a slow or
	down Acumatica never holds up the user's save."""
	if frappe.flags.in_demo_seed:
		# demo data's Won deals must not become customers in a real ERP
		return
	settings = get_settings()
	if (
		not settings.enabled
		or not settings.create_customer_on_status_change
		or doc.status != settings.deal_status
		or not doc.organization
	):
		return

	frappe.enqueue(
		"crm.integrations.acumatica.outbound.push_customer_for_deal",
		deal=doc.name,
		queue="short",
		job_id=f"acumatica_customer_{doc.organization}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def create_customer_in_acumatica(doc, method):
	"""Deprecated: renamed to queue_customer_push. Kept as a thin alias for one
	release so a site with a stale hooks cache (pointing at the old dotted path)
	does not error before it picks up the new hooks.py."""
	return queue_customer_push(doc, method)


def push_customer_for_deal(deal: str) -> None:
	"""Worker: does the actual Acumatica customer push. Re-loads the deal and
	re-checks the conditions, since time has passed since the hook enqueued this
	and the deal's status may have moved on."""
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
		return

	client = AcumaticaClient(settings)
	payload = {"CustomerName": org.organization_name}
	if settings.customer_numbering == "From Organization Name":
		# Acumatica's default CUSTOMER ID segment is 10; the setting exists for
		# tenants that widened it.
		limit = int(settings.get("customer_id_max_length") or 10)
		payload["CustomerID"] = re.sub(r"[^A-Z0-9]", "", org.organization_name.upper())[:limit]

	inflight = _inflight_key("Customer", org.name)
	if frappe.cache().get_value(inflight):
		# An earlier push never heard back, and the next deal save fired this one. Under
		# AutoNumber a second PUT is a second customer; under From Organization Name the
		# collision check below would refuse the id the first one took. Link what it
		# made instead.
		try:
			earlier = _earlier_customer(client, payload)
		except (AcumaticaError, requests.RequestException, ValueError) as e:
			record_sync_issue(
				"Customer",
				org.name,
				"Push Failed",
				f"could not look for the customer an unanswered push may have created: {e} :: {_reason(e)}",
			)
			return
		if earlier:
			_link_customer(org.name, doc.name, earlier)
			_settle_inflight(inflight)
			return

	if payload.get("CustomerID"):
		collision = _customer_id_collision(client, payload["CustomerID"], org.name)
		if collision:
			record_sync_issue("Customer", org.name, "Push Failed", collision)
			return

	# enqueue_after_commit only defers the ENQUEUE into frappe.db.after_commit -- a plain
	# deque with no de-duplication of its own. Two deals on the same organization saved
	# inside one request both pass queue_customer_push's redis dedup check at hook time
	# (nothing has committed yet, so neither looks like a duplicate to the other) and
	# both land a job at commit; two workers then reach this point concurrently, and the
	# unlocked read above can't see a link a concurrent winner is mid-write on. Re-read
	# with a row lock immediately before the PUT: the loser blocks here until the
	# winner's write below commits, then sees the link already populated and no-ops
	# instead of PUTting a second Customer into the client's ERP.
	locked = frappe.db.get_value(
		"CRM Organization", org.name, ["acumatica_noteid", "acumatica_id"], as_dict=True, for_update=True
	)
	if locked and (locked.acumatica_noteid or locked.acumatica_id):
		if not doc.get("acumatica_customer") and locked.acumatica_id:
			frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", locked.acumatica_id)
		return

	_mark_inflight(inflight)
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
		record_sync_issue("Customer", org.name, "Push Failed", detail)
		return

	_link_customer(org.name, doc.name, created)
	_settle_inflight(inflight)


def _link_customer(org_name: str, deal_name: str, customer) -> None:
	frappe.db.set_value(
		"CRM Organization",
		org_name,
		{"acumatica_noteid": v(customer, "NoteID"), "acumatica_id": v(customer, "CustomerID")},
	)
	frappe.db.set_value("CRM Deal", deal_name, "acumatica_customer", v(customer, "CustomerID"))


def _earlier_customer(client, payload: dict):
	"""The customer an unanswered push may have created, or None. Under From
	Organization Name it carries the id the push sent; under AutoNumber only the name.
	Two customers by that name is not a guess to make on the client's ERP."""
	if payload.get("CustomerID"):
		filter_ = f"CustomerID eq {_odata(payload['CustomerID'])}"
	else:
		filter_ = f"CustomerName eq {_odata(payload['CustomerName'])}"
	page = client.get_page("Customer", top=2, filter=filter_, orderby=None)
	if len(page) > 1:
		raise AcumaticaError(
			f"Acumatica has more than one customer named {payload['CustomerName']}; link the right one by hand"
		)
	return page[0] if page else None


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
