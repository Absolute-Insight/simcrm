"""Close CRM deals from what happened to their quote in Acumatica.

A quote a customer accepts is copied into a sales order and the quote itself is
marked Completed; one they decline is Canceled or Rejected. The deal in the CRM
knows its quote number (``acumatica_sales_quote``, set by the spreadsheet import
and by Create Sales Quote), so the nightly sweep reads the quotes changed since
its high-water mark and closes the matching deals. Without this a deal stayed
open until a rep closed it by hand -- twice, once per system -- and the open
pipeline never shrank.

Acumatica never expires a quote (2,144 sat Open on MBP's tenant regardless of
age), so the validity rule is applied here: a deal whose quote is still open past
its validity date plus a grace period is Lost as expired, unless a rep touched
it recently -- somebody working it is the one who decides.
"""

from __future__ import annotations

import time
from datetime import datetime

import frappe
from frappe.utils import add_days, getdate, nowdate

from crm.integrations.acumatica.client import v

LOST_CANCELLED = "Quote cancelled in Acumatica"
LOST_REJECTED = "Quote rejected in Acumatica"
LOST_EXPIRED = "Quote expired"

WON_STATUSES = ("Completed",)
LOST_STATUSES = {"Canceled": LOST_CANCELLED, "Rejected": LOST_REJECTED}

PAGE = 500
# A rep who edited the deal this recently is working it; the expiry rule waits.
RECENT_TOUCH_DAYS = 14


def _ensure_lost_reason(reason: str) -> None:
	if not frappe.db.exists("CRM Lost Reason", reason):
		frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": reason}).insert(ignore_permissions=True)


def _open_deals_by_quote() -> dict[str, str]:
	rows = frappe.get_all(
		"CRM Deal",
		filters={"acumatica_sales_quote": ["is", "set"], "status": ["not in", ["Won", "Lost"]]},
		fields=["name", "acumatica_sales_quote"],
		limit=100000,
	)
	return {row.acumatica_sales_quote: row.name for row in rows}


def _close(deal_name: str, status: str, lost_reason: str | None = None, closed_on=None) -> None:
	doc = frappe.get_doc("CRM Deal", deal_name)
	doc.status = status
	if lost_reason:
		_ensure_lost_reason(lost_reason)
		doc.lost_reason = lost_reason
	doc.flags.ignore_permissions = True
	doc.save()
	if status == "Won" and closed_on:
		# validate() stamps today on the way into Won; the quote says when it really was
		doc.db_set("closed_date", closed_on, update_modified=False)


def _date_of(value) -> datetime | None:
	if not value:
		return None
	try:
		return getdate(str(value)[:10])
	except Exception:
		return None


def pull_quote_outcomes(client, modified_since: str | None) -> dict:
	"""Read quotes changed since ``modified_since`` and close the deals they decide.

	One page of quotes is one request; a full history is a handful. Deals a rep
	has already closed are left alone -- the rep's word stands.
	"""
	counts = {"won": 0, "lost": 0, "unchanged": 0}
	by_quote = _open_deals_by_quote()
	if not by_quote:
		return counts
	order_type = getattr(client.settings, "quote_order_type", None) or "QT"
	filter_ = f"OrderType eq '{order_type}'"
	if modified_since:
		# SalesOrder's modification stamp is `LastModified`, not `LastModifiedDateTime`
		filter_ += f" and LastModified gt datetimeoffset'{str(modified_since).replace(' ', 'T')}Z'"
	pause = float(getattr(client.settings, "request_pause", 0) or 0)
	skip = 0
	while True:
		page = client.get_page(
			"SalesOrder", top=PAGE, skip=skip, filter=filter_, select="OrderNbr,Status,LastModified"
		)
		if not page:
			break
		for quote in page:
			deal = by_quote.get(v(quote, "OrderNbr"))
			if not deal:
				continue
			status = v(quote, "Status")
			if status in WON_STATUSES:
				_close(deal, "Won", closed_on=_date_of(v(quote, "LastModified")))
				counts["won"] += 1
			elif status in LOST_STATUSES:
				_close(deal, "Lost", lost_reason=LOST_STATUSES[status])
				counts["lost"] += 1
			else:
				counts["unchanged"] += 1
		skip += len(page)
		if pause:
			time.sleep(pause)
	return counts


def expire_stale_quotes(grace_days: int) -> dict:
	"""Lose, as expired, every open deal whose quote is past validity plus grace.

	``expected_closure_date`` is the quote's validity date (the import set it to the
	quote date plus the validity period). Zero grace switches the rule off. A deal a
	rep edited within :data:`RECENT_TOUCH_DAYS` is left to them.
	"""
	if not grace_days or int(grace_days) <= 0:
		return {"expired": 0}
	cutoff = add_days(nowdate(), -int(grace_days))
	touched_after = add_days(nowdate(), -RECENT_TOUCH_DAYS)
	stale = frappe.get_all(
		"CRM Deal",
		filters={
			"acumatica_sales_quote": ["is", "set"],
			"status": ["not in", ["Won", "Lost"]],
			"expected_closure_date": ["<", cutoff],
			"modified": ["<", touched_after],
		},
		pluck="name",
		limit=100000,
	)
	for name in stale:
		_close(name, "Lost", lost_reason=LOST_EXPIRED)
	return {"expired": len(stale)}
