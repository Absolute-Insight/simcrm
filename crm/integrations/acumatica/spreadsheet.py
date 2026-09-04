"""One-way import of MBP's Acumatica Excel exports.

Not the live sync (``importer.py``) -- that needs the integration on. This reads
four ``.xlsx`` files and writes organizations, addresses, deals and revenue
through the same upserts the live sync uses, so a later sync adopts what this
wrote instead of creating rivals. Design and every mapping decision:
docs/superpowers/specs/2026-09-03-mbp-acumatica-import-design.md.

The transforms are pure so the rules that can corrupt data silently are the
ones with direct tests.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import frappe
from openpyxl import load_workbook

from crm.integrations.acumatica.importer import COMMIT_EVERY, upsert_organization

# Payment terms leaking into the customer name. Only this suffix is stripped:
# "- Shaft 10", "- Driefontein Division" and the like are real delivery sites.
_COD_SUFFIX = re.compile(r"\s-\s[Cc][Oo][Dd]\s*$")

PLACEHOLDER_EMAILS = {"no@email.co.za"}

# The stage every imported open quote lands in: a quote has been issued and
# nothing in the file says more than that.
OPEN_STATUS = "Proposal/Quotation"

_OPEN_STATUSES = {"Open", "On Hold", "Pending Approval"}
_LOST_STATUSES = {"Canceled", "Rejected"}


def normalise_account_name(name: str) -> str:
	return _COD_SUFFIX.sub("", (name or "").strip()).strip()


def usable_email(value) -> str | None:
	"""A single real address, or nothing. A statement mailbox list is not a sales contact."""
	if not value:
		return None
	value = str(value).strip().lower()
	if not value or ";" in value or "," in value or "@" not in value:
		return None
	if value in PLACEHOLDER_EMAILS:
		return None
	return value


def normalise_phone(value) -> str | None:
	if value is None:
		return None
	raw = str(value).strip()
	if not raw:
		return None
	digits = re.sub(r"\D", "", raw)
	if raw.startswith("+"):
		return "+" + digits
	if len(digits) == 10 and digits.startswith("0"):
		return "+27" + digits[1:]
	return digits or None


def map_country(iso2, table: dict[str, str]) -> str | None:
	"""``table`` is ``{lowercase ISO-2 code: Country name}`` -- frappe stores ``Country.code``
	lowercase, and ``NA`` must reach here as a string, not a null."""
	if not iso2:
		return None
	return table.get(str(iso2).strip().lower())


def to_decimal(value) -> Decimal:
	"""openpyxl hands back floats; ``Decimal(str(x))`` keeps the decimal the sheet shows
	rather than the binary expansion ``Decimal(x)`` would carry in."""
	if value is None or value == "":
		return Decimal("0")
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def map_deal_status(status: str, outcome) -> str | None:
	"""For ``Order Type = QT`` rows only. ``Quote Outcome`` records only failure, so it wins;
	``Completed`` is read as converted to an order. Unknown combinations return None
	and the caller rejects the row rather than guessing."""
	if outcome == "Lost":
		return "Lost"
	if status in _LOST_STATUSES:
		return "Lost"
	if status == "Completed":
		return "Won"
	if status in _OPEN_STATUSES:
		return OPEN_STATUS
	return None


def within_window(quote_date: date, as_of: date, days: int) -> bool:
	return quote_date >= as_of - timedelta(days=days)


def read_sheet(path, sheet: str = "Data") -> list[dict]:
	"""The workbook, not an export of it: a CSV round-trip re-introduces DD/MM ambiguity
	the source does not have, and a MM/DD misread only errors on days above 12."""
	path = Path(path)
	if path.suffix.lower() != ".xlsx":
		raise ValueError(f"{path.name}: the importer reads .xlsx workbooks only, never CSV")
	wb = load_workbook(path, read_only=True, data_only=True)
	try:
		ws = wb[sheet]
		rows_iter = ws.iter_rows(values_only=True)
		header = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
		return [
			dict(zip(header, row, strict=True)) for row in rows_iter if any(cell is not None for cell in row)
		]
	finally:
		wb.close()


class Rejects:
	"""Rows the import would not write, and why. Reported at the end, never skipped silently:
	a row that fails to resolve its organization, salesperson or status is a finding
	about the mapping."""

	def __init__(self):
		self.rows: list[dict] = []

	def add(self, file: str, key, reason: str) -> None:
		self.rows.append({"file": file, "key": str(key), "reason": reason})

	def __len__(self) -> int:
		return len(self.rows)


def _commit_every(done: int) -> None:
	# Same reasoning as run_backfill: a 10k-row import must not hold one transaction.
	# Under test the whole run is one rolled-back transaction, so never commit there.
	if done % COMMIT_EVERY == 0 and not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit


def _country_table() -> dict[str, str]:
	return {
		(row.code or "").lower(): row.name
		for row in frappe.get_all("Country", fields=["name", "code"])
		if row.code
	}


def dedupe_customers(rows: list[dict]) -> list[dict]:
	"""Two customer IDs appear twice in the export; the second would silently overwrite
	the first. Keep the row flagged Default, else the first seen."""
	by_id: dict[str, dict] = {}
	for row in rows:
		cid = row.get("Customer ID")
		if not cid:
			continue
		if cid not in by_id or str(row.get("Default")) == "True":
			by_id[cid] = row
	return list(by_id.values())


def shape_customer(row: dict, countries: dict[str, str] | None = None) -> dict:
	"""One export row -> what the upserts take. ``countries`` is the ISO-2 table; pass None
	to leave the country unresolved (the pure tests do)."""
	countries = countries or {}
	name = normalise_account_name(row.get("Customer Name") or "")
	rec = {
		"CustomerID": {"value": row.get("Customer ID")},
		"CustomerName": {"value": name},
		"CurrencyID": {"value": row.get("Currency ID")},
	}
	line1 = (row.get("Address Line 1") or "").strip()
	city = (row.get("City") or "").strip()
	address = None
	if line1 and city:
		address = {
			"address_line1": line1,
			"address_line2": (row.get("Address Line 2") or "").strip() or None,
			"city": city,
			"state": (row.get("State") or "").strip() or None,
			"pincode": str(row.get("Postal Code") or "").strip() or None,
			"country": map_country(row.get("Country"), countries),
			"email_id": usable_email(row.get("Email")),
			"phone": normalise_phone(row.get("Phone 1")),
		}
	return {
		"customer_id": row.get("Customer ID"),
		"status": row.get("Customer Status"),
		"rec": rec,
		"address": address,
	}


def upsert_address(organization: str, fields: dict) -> str:
	"""Keyed on the Dynamic Link back to the organization, so a re-run edits the same row."""
	existing = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "CRM Organization", "link_name": organization, "parenttype": "Address"},
		"parent",
	)
	doc = frappe.get_doc("Address", existing) if existing else frappe.new_doc("Address")
	doc.update({k: v for k, v in fields.items() if v is not None})
	for key, value in fields.items():
		if value is None:
			doc.set(key, None)
	doc.address_title = organization
	doc.address_type = "Billing"
	if not existing:
		doc.append("links", {"link_doctype": "CRM Organization", "link_name": organization})
	doc.save(ignore_permissions=True)
	frappe.db.set_value("CRM Organization", organization, "address", doc.name, update_modified=False)
	return doc.name


def import_customers(path, rejects: Rejects) -> dict:
	counts = {"organizations": 0, "addresses": 0, "skipped_inactive": 0, "addresses_skipped": 0}
	countries = _country_table()
	rows = dedupe_customers(read_sheet(path))
	for done, row in enumerate(rows, 1):
		shaped = shape_customer(row, countries)
		if shaped["status"] == "Inactive":
			counts["skipped_inactive"] += 1
			continue
		frappe.db.savepoint("ss_customer")
		try:
			if not shaped["rec"]["CustomerName"]["value"]:
				raise ValueError("no customer name")
			org = upsert_organization(shaped["rec"])
			counts["organizations"] += 1
			if shaped["address"]:
				if shaped["address"]["country"] is None and row.get("Country"):
					raise ValueError(f"unknown country code {row.get('Country')!r}")
				upsert_address(org, shaped["address"])
				counts["addresses"] += 1
			else:
				counts["addresses_skipped"] += 1
		except Exception as e:
			frappe.db.rollback(save_point="ss_customer")
			rejects.add("customers", shaped["customer_id"], str(e))
		_commit_every(done)
	return counts
