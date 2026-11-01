"""Make a CRM deal for every quote raised in Acumatica that no deal carries yet.

The 2026-09-05 spreadsheet import turned the quotes of the day into deals, and the
nightly sweep only ever closed deals that already held a quote number
(``outcomes.py``). A quote raised in Acumatica after the import therefore never
reached the CRM: won revenue stopped at the import, and October read as nothing
won. This pass reads the same quotes the outcome pass reads -- the configured order
type, changed since the high-water mark -- and writes a deal for each new one through
the spreadsheet import's own ``upsert_deal``, so both paths make the same deal.

Off unless an admin turns it on (``create_deals_from_quotes``), and bounded below by
a quote date (``create_deals_from_quotes_since``): a full backfill reads every quote
the tenant ever had, and the import deliberately left the old open ones out.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_system_timezone, getdate, now_datetime

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import record_sync_issue
from crm.integrations.acumatica import outcomes
from crm.integrations.acumatica.client import v
from crm.integrations.acumatica.importer import COMMIT_EVERY, MAX_RETRY_ATTEMPTS
from crm.integrations.acumatica.outbound import QUOTE_DESCRIPTION_PREFIX
from crm.integrations.acumatica.spreadsheet import OPEN_STATUS, created_on, to_decimal, upsert_deal

try:
	from rq.timeouts import JobTimeoutException
except ImportError:  # pragma: no cover - rq is a frappe dependency; guard for bench-less imports

	class JobTimeoutException(BaseException):
		"""Stand-in that is never raised, so the except clauses below stay valid."""


# The key of this pass's work list in pending_retries, and the entity its sync issues name.
QUEUE = "SalesQuote"
# MBP's quotes are good for 30 days; the spreadsheet import assumed the same.
QUOTE_VALIDITY_DAYS = 30
# Who owns a deal whose quote names no salesperson, or one nobody mapped -- as the
# import's default owner did. Somebody has to, or the deal is invisible to every rep.
DEFAULT_OWNER = "Administrator"
# The salesperson on a quote is in its Commissions section, not in the header.
EXPAND = "Commissions"
# Set when the switch is turned on, or its date floor moved earlier: the high-water
# mark is past every quote raised before then, so the next pass reads all quotes
# (the floor still applies) -- once, cleared only when that pass has finished.
REREAD_ALL_NEW_QUOTES = "acumatica_reread_all_new_quotes"
# Who may own a deal the sync makes: the roles a rep or a sales manager holds.
OWNER_ROLES = ("Sales User", "Sales Manager")


def parse_owner_map(raw) -> dict[str, str]:
	"""``{"<salesperson ID>": "<user>"}`` from the settings field, or a ValueError
	that says what is wrong with it. Empty is an empty map."""
	if not raw:
		return {}
	if isinstance(raw, dict):
		data = raw
	else:
		try:
			data = json.loads(raw)
		except ValueError as e:
			raise ValueError(_("Salesperson Owners is not valid JSON: {0}").format(str(e))) from e
	if not isinstance(data, dict):
		raise ValueError(_("Salesperson Owners must be a JSON object of salesperson ID to user"))
	out = {}
	for code, user in data.items():
		code = str(code).strip()
		if not code or not isinstance(user, str) or not user.strip():
			raise ValueError(_("Salesperson Owners: {0} must map to a user's email").format(code or '""'))
		out[code] = user.strip()
	return out


def _odata(value: str) -> str:
	return "'" + str(value).replace("'", "''") + "'"


def _local(value) -> datetime | None:
	"""An Acumatica timestamp as naive site-local time, which is what ``creation`` holds."""
	if not value:
		return None
	try:
		parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
	except ValueError:
		return None
	if parsed.tzinfo:
		parsed = parsed.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return parsed


def _salesperson(quote) -> str | None:
	commissions = quote.get("Commissions") if isinstance(quote, dict) else None
	code = v(commissions, "DefaultSalesperson") or v(quote, "DefaultSalesperson")
	return str(code).strip() if code else None


class _Pass:
	"""One run's state: what the CRM already has, and who owns what."""

	def __init__(self, client, settings, pending: dict, counts: dict):
		self.client = client
		self.pending = pending
		self.counts = counts
		since = settings.get("create_deals_from_quotes_since")
		self.since = getdate(since) if since else None
		try:
			self.owners = parse_owner_map(settings.get("salesperson_owners"))
		except ValueError as e:
			# settings validation refuses this, so it was written past it; say so once
			# and carry on with Administrator rather than stop the sync
			self.owners = {}
			self._log_once("Settings", "salesperson_owners", "Mapping Conflict", str(e))
		self.base_currency = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
		self.known = set(
			frappe.get_all(
				"CRM Deal", filters={"acumatica_sales_quote": ["is", "set"]}, pluck="acumatica_sales_quote"
			)
		)
		self.usable_users: dict[str, bool] = {}
		self.unmapped_logged: set[str] = set()
		self.created = 0

	# --- one quote ---------------------------------------------------------
	def consider(self, quote) -> None:
		"""Write a deal for ``quote`` if it is new and wanted. Raises on a quote that
		should have become a deal and could not."""
		nbr = v(quote, "OrderNbr")
		if not nbr or nbr in self.known:
			return
		if self._is_ours(quote, nbr):
			return
		total = to_decimal(v(quote, "OrderTotal"))
		if total <= 0:
			# the import never wrote one either: a quote with no value is a draft or a
			# placeholder, and forecasting refuses a deal without an expected value
			self.counts["quotes_skipped"] += 1
			return
		quote_date = outcomes.date_of(v(quote, "Date"))
		if not quote_date:
			raise ValueError(_("quote {0} has no date").format(nbr))
		if self.since and quote_date < self.since:
			self.counts["quotes_skipped"] += 1
			return
		if self._deleted_by_a_rep(nbr):
			# the rep's word stands: a deal somebody deleted does not come back
			self.counts["quotes_skipped"] += 1
			return

		customer_id = v(quote, "CustomerID")
		organization = (
			frappe.db.get_value("CRM Organization", {"acumatica_id": customer_id}, "name")
			if customer_id
			else None
		)
		if not organization:
			raise ValueError(_("customer {0} has no organization in the CRM").format(customer_id or "?"))

		status, lost_reason = _deal_status(v(quote, "Status"))
		closed_date = None
		if status in ("Won", "Lost"):
			# when it was accepted or declined, as the outcome pass dates a close
			closed_date = max(outcomes.date_of(v(quote, "LastModified")) or quote_date, quote_date)
			if lost_reason:
				outcomes.ensure_lost_reason(lost_reason)
		currency = v(quote, "CurrencyID") or self.base_currency
		created = min(created_on(_local(v(quote, "CreatedDate")), quote_date), now_datetime())

		deal = {
			"order_nbr": nbr,
			"customer_id": customer_id,
			"status": status,
			"lost_reason": lost_reason,
			"value": total,
			"currency": currency,
			# None for a foreign currency: the deal controller fetches the rate, as it
			# does for a deal a rep types in
			"exchange_rate": 1 if currency == self.base_currency else None,
			"owner": self._owner(_salesperson(quote)),
			"closed_date": closed_date,
			"expected_closure_date": closed_date or quote_date + timedelta(days=QUOTE_VALIDITY_DAYS),
			"created_on": created,
		}
		if upsert_deal(deal, organization):
			self.known.add(nbr)
			self.counts["new_deals"] += 1
			self.created += 1
			if self.created % COMMIT_EVERY == 0 and not frappe.flags.in_test:
				# same reasoning as the entity loops: a first pass over months of quotes
				# must not hold one transaction
				frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def _is_ours(self, quote, nbr: str) -> bool:
		"""A quote the CRM's own Create Sales Quote made, adopted by the deal that made it.

		The deal stores the number once Acumatica answers; a sweep that reads the quote
		first must not make the same opportunity a second deal. Matched as
		``outbound._earlier_quote`` matches an unanswered attempt -- Description AND
		customer -- and only onto a deal still without a quote. A deal that already has
		one is not this quote's: a copy of a CRM-made quote carries its Description too,
		and is a deal of its own rather than revenue that never arrives."""
		description = v(quote, "Description") or ""
		if not description.startswith(QUOTE_DESCRIPTION_PREFIX):
			return False
		name = description[len(QUOTE_DESCRIPTION_PREFIX) :].strip()
		deal = (
			frappe.db.get_value(
				"CRM Deal",
				name,
				["acumatica_sales_quote", "acumatica_customer", "organization"],
				as_dict=True,
			)
			if name
			else None
		)
		if deal and deal.acumatica_sales_quote == nbr:
			# Create Sales Quote stored this number after the pass listed the known
			# ones: already this deal's, and upsert_deal must not overwrite it
			self.known.add(nbr)
			return True
		if not deal or deal.acumatica_sales_quote:
			return False
		customer = deal.acumatica_customer or (
			frappe.db.get_value("CRM Organization", deal.organization, "acumatica_id")
			if deal.organization
			else None
		)
		if not customer or customer != v(quote, "CustomerID"):
			return False
		frappe.db.set_value("CRM Deal", name, "acumatica_sales_quote", nbr, update_modified=False)
		self.counts["linked_quotes"] += 1
		self.known.add(nbr)
		return True

	def _deleted_by_a_rep(self, nbr: str) -> bool:
		# Deleted Document keeps the deal as frappe.as_json wrote it; asked only for a
		# quote that is otherwise about to become a deal, so a handful of reads a night
		return bool(
			frappe.db.exists(
				"Deleted Document",
				{"deleted_doctype": "CRM Deal", "data": ["like", f'%"acumatica_sales_quote": "{nbr}"%']},
			)
		)

	def _owner(self, code: str | None) -> str:
		if not code:
			return DEFAULT_OWNER
		user = self.owners.get(code)
		if user and self._usable(user):
			return user
		if code not in self.unmapped_logged:
			self.unmapped_logged.add(code)
			detail = (
				f"salesperson {code} maps to {user}, who cannot own deals ({_owner_problem(user)}); their quotes go to {DEFAULT_OWNER}"
				if user
				else f"salesperson {code} is not in Salesperson Owners; their quotes go to {DEFAULT_OWNER}"
			)
			self._log_once("Salesperson", code, "Mapping Conflict", detail)
		return DEFAULT_OWNER

	def _usable(self, user: str) -> bool:
		if user not in self.usable_users:
			# the settings check, again: a rep disabled or demoted since it was saved
			self.usable_users[user] = _owner_problem(user) is None
		return self.usable_users[user]

	@staticmethod
	def _log_once(entity: str, remote_id: str, kind: str, detail: str) -> None:
		"""One open row per salesperson: the same unmapped code turns up every night."""
		try:
			issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
			if any(r.entity == entity and r.remote_id == remote_id and not r.dismissed for r in issues):
				return
			record_sync_issue(entity, remote_id, kind, detail)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Acumatica sync issue recording failed")

	# --- failures ------------------------------------------------------------
	def attempt(self, quote) -> Exception | None:
		"""``consider`` under a savepoint of its own: the failure, or None."""
		frappe.db.savepoint("acumatica_quote")
		try:
			self.consider(quote)
			return None
		except JobTimeoutException:
			# the run's deadline, not this quote's fault (see importer._retry_pending)
			frappe.db.rollback(save_point="acumatica_quote")
			raise
		except Exception as e:
			frappe.db.rollback(save_point="acumatica_quote")
			return e


def _deal_status(status) -> tuple[str, str | None]:
	"""Acumatica's quote status as a deal status, by the rules the outcome pass closes
	deals with: Completed is converted to an order and won, Canceled and Rejected are
	lost for Acumatica's reason, and anything else is a quote still out with the customer."""
	if status in outcomes.WON_STATUSES:
		return "Won", None
	if status in outcomes.LOST_STATUSES:
		return "Lost", outcomes.LOST_STATUSES[status]
	return OPEN_STATUS, None


def _log_issue(nbr: str, kind: str, detail: str) -> None:
	try:
		record_sync_issue(QUEUE, nbr, kind, detail)
	except Exception:
		# losing the ability to log one bad quote must not abort the rest of the run
		frappe.log_error(frappe.get_traceback(), "Acumatica sync issue recording failed")


def pull_new_quotes(client, modified_since: str | None, pending: dict, settings) -> dict:
	"""Create a deal for each quote changed since ``modified_since`` that no deal has.

	A quote that should have become a deal and could not -- its customer has not
	reached the CRM yet, a validation the deal fails -- is logged once and queued in
	``pending`` like a failed customer: the high-water mark moves past it, so it is
	fetched again by number on the next sweeps until it lands or runs out of attempts.
	"""
	counts = {"new_deals": 0, "linked_quotes": 0, "quotes_skipped": 0, "quote_issues": 0}
	reread = bool(frappe.db.get_default(REREAD_ALL_NEW_QUOTES))
	if reread:
		modified_since = None
	quiet = frappe.flags.bulk_assign_quietly
	# a night's quotes are assigned in one run, with nobody at a desk to read them:
	# the ToDo is the assignment, and no email or job per deal (the rep gets one in-app notification)
	frappe.flags.bulk_assign_quietly = True
	try:
		run = _Pass(client, settings, pending, counts)
		retried = _retry_queued(run, client)
		_page_quotes(run, client, modified_since, retried)
	finally:
		frappe.flags.bulk_assign_quietly = quiet
	if reread:
		# only once every page has been read: a run that died part-way asks again
		frappe.defaults.clear_default(REREAD_ALL_NEW_QUOTES)
	return counts


def _retry_queued(run: _Pass, client) -> set[str]:
	queued = run.pending.get(QUEUE) or {}
	pause = float(getattr(client.settings, "request_pause", 0) or 0)
	tried = set(queued)
	for nbr, attempts in list(queued.items()):
		if nbr in run.known:
			del queued[nbr]
			continue
		# a fetch that fails here is a run-level failure, as in the paging pass below
		page = client.get_page(
			"SalesOrder",
			top=1,
			filter=f"OrderType eq {_odata(outcomes.quote_order_type(client))} and OrderNbr eq {_odata(nbr)}",
			expand=EXPAND,
			orderby=None,
		)
		if pause:
			time.sleep(pause)
		if not page:
			# deleted in Acumatica since: nothing left to make a deal of
			del queued[nbr]
			continue
		error = run.attempt(page[0])
		if error is None:
			del queued[nbr]
			continue
		attempts += 1
		if attempts < MAX_RETRY_ATTEMPTS:
			queued[nbr] = attempts
			continue
		del queued[nbr]
		run.counts["quote_issues"] += 1
		_log_issue(nbr, "Gave Up", str(error))
	if not queued:
		run.pending.pop(QUEUE, None)
	# the paging pass leaves all of these alone: each had its attempt tonight
	return tried


def _page_quotes(run: _Pass, client, modified_since: str | None, retried: set[str]) -> None:
	filter_ = outcomes.quote_filter(client, modified_since)
	pause = float(getattr(client.settings, "request_pause", 0) or 0)
	skip = 0
	while True:
		page = client.get_page("SalesOrder", top=outcomes.PAGE, skip=skip, filter=filter_, expand=EXPAND)
		if not page:
			break
		for quote in page:
			nbr = v(quote, "OrderNbr")
			if nbr in retried:
				continue
			error = run.attempt(quote)
			if error is None:
				continue
			run.counts["quote_issues"] += 1
			_log_issue(nbr or "?", "Import Failed", str(error))
			if nbr:
				# setdefault, as importer._import_entities: a backfill re-reads a quote
				# the retry pass already counted
				run.pending.setdefault(QUEUE, {}).setdefault(nbr, 1)
		skip += len(page)
		if pause:
			time.sleep(pause)


def validate_settings(doc, before=None) -> None:
	"""Called from the settings controller's validate: refuse a mapping the sweep
	cannot read or a user who could not own a deal, and the switch without its date
	floor; and ask the next sweep to read every quote when the switch is turned on or
	its floor moved earlier. ``before`` is the saved settings (None on a first save)."""
	if before is None and hasattr(doc, "get_doc_before_save"):
		before = doc.get_doc_before_save()
	before = before or frappe._dict()
	try:
		owners = parse_owner_map(doc.get("salesperson_owners"))
	except ValueError as e:
		frappe.throw(str(e))
	switched_on = bool(doc.get("create_deals_from_quotes"))
	# Users are checked when it matters, not on every save: one deleted later must
	# not block an unrelated edit while the switch is off.
	if switched_on or doc.get("salesperson_owners") != before.get("salesperson_owners"):
		problems = [_owner_problem(user) for user in sorted(set(owners.values()))]
		problems = [p for p in problems if p]
		if problems:
			frappe.throw("; ".join(problems), title=_("Salesperson Owners"))
	if not switched_on:
		return
	since = doc.get("create_deals_from_quotes_since")
	if not since:
		frappe.throw(
			_("Set Quotes Dated From before turning on Create Deals from New Quotes"),
			title=_("Missing date"),
		)
	was_on = bool(before.get("create_deals_from_quotes"))
	old_since = before.get("create_deals_from_quotes_since")
	if not was_on or not old_since or getdate(since) < getdate(old_since):
		frappe.db.set_default(REREAD_ALL_NEW_QUOTES, 1)


def _owner_problem(user: str) -> str | None:
	"""Why ``user`` cannot own the deals the sync makes, or None."""
	if user in ("Guest", "Administrator"):
		return _("{0} cannot own synced deals; map the salesperson to a rep").format(
			frappe.utils.escape_html(user)
		)
	row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not row:
		return _("{0} is not a user").format(frappe.utils.escape_html(user))
	if not row.enabled:
		return _("{0} is disabled").format(frappe.utils.escape_html(user))
	if row.user_type != "System User":
		return _("{0} is not a System User").format(frappe.utils.escape_html(user))
	if not set(frappe.get_roles(user)) & set(OWNER_ROLES):
		return _("{0} has neither the Sales User nor the Sales Manager role").format(
			frappe.utils.escape_html(user)
		)
	return None
