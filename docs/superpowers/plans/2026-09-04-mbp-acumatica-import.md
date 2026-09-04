# MBP Acumatica Spreadsheet Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A re-runnable `bench execute` entry point that loads MBP's four Acumatica `.xlsx` exports into the production site as organizations, addresses, deals and per-organization revenue, with a dry-run and a reject report.

**Architecture:** One new module, `crm/integrations/acumatica/spreadsheet.py`, split into pure transforms (no Frappe, unit-tested), row shapers that produce the `{"value": x}` records the existing `upsert_organization` already consumes, and three importers driven by one entry point. Identity reuses the live sync's keys — `acumatica_id` on organizations, `acumatica_sales_quote` on deals — so a later live sync adopts what the import wrote. Two small guards land in `importer.py` first so the shared path is safe without a `NoteID`.

**Tech Stack:** Frappe (Python, tabs), `openpyxl` 3.1.5 (already in the bench env), `decimal.Decimal`, `frappe.tests.UnitTestCase` / `IntegrationTestCase`.

**Spec:** `docs/superpowers/specs/2026-09-03-mbp-acumatica-import-design.md` — read it first; every mapping and threshold below is argued there.

## Global Constraints

Copied from the spec. Every task's requirements include these.

- **Read the `.xlsx` directly; refuse CSV.** openpyxl returns native `datetime` for every date cell. A CSV round-trip re-introduces DD/MM ambiguity that fails silently for days ≤ 12.
- **Money:** openpyxl returns floats. Convert with `Decimal(str(x))`, never `Decimal(x)`.
- **Currency is per row.** Sales Orders carry 30 USD rows; Invoices 7; Customers 4. Never sum mixed currencies. The site's base currency is `FCRM Settings.currency` and **must be `ZAR`** before the import runs (the deal controller fetches a live rate for anything else).
- **Country is ISO-2**, matched to Frappe's `Country.code`, which is stored **lowercase** (`"za"`). `NA` is Namibia, not null.
- **Email:** import only a single address that is not a placeholder. Drop `no@email.co.za` and any value containing `;`.
- **Phone:** local SA format (`0792530729`); normalise to `+27…`.
- **Organization name:** strip a trailing ` - COD` / ` - Cod` only. Every other suffix stays.
- **Deduplicate Customers on `Customer ID`** before writing; prefer the row with `Default = "True"`.
- **Deals come only from `Order Type = QT`.** `SO`, `TR`, `CM` are excluded, not rejected.
- **Open quotes are windowed** (default 90 days from the export's latest `Date`); won and lost are imported regardless of age.
- **Every imported deal sets `expected_deal_value` and `expected_closure_date`** — the deal controller throws without them when forecasting is on.
- **Won deals need `closed_date` written after save** (`validate` stamps today on any transition into Won). **Lost deals need a `lost_reason`** (`validate_lost_reason` throws without one).
- **Rejected rows are reported, never skipped silently.** Excluded row types are counted, not reported.
- **Idempotent:** organizations key on `acumatica_id`, deals on `acumatica_sales_quote`, addresses on their Dynamic Link to the organization. A manifest of created deal keys stops a re-run resurrecting a deal a rep deleted.
- **No commits under test.** Mirror `run_backfill`: commit every 50 records only when `not frappe.flags.in_test`.
- **The MBP files are never committed.** Tests build their own workbooks with openpyxl in a temp dir.
- **Tests run inside the devcontainer** at `/home/frappe/frappe-bench`, against `test_site`, never the browsing site:
  `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`.
- Python is **tab-indented** in this repo. Pre-commit runs ruff.

---

## File Structure

| File | Responsibility |
|---|---|
| `crm/integrations/acumatica/importer.py` (modify) | Two guards so `upsert_organization` is safe without a `NoteID`, and adopts by `acumatica_id`. |
| `crm/integrations/acumatica/spreadsheet.py` (create) | Pure transforms, the workbook reader, the three importers, the entry point. |
| `crm/integrations/acumatica/test_spreadsheet.py` (create) | Unit tests for the transforms; integration tests for each importer against `test_site`. |
| `crm/integrations/acumatica/test_importer.py` (modify) | Two tests for the new guards. |
| `.pi/feats/acumatica/README.md` (modify) | A short section pointing at the spreadsheet import and its runbook. |

The transforms carry all the silent-corruption risk, so they are separate functions with no I/O. The importers are thin: shape a row, call an upsert, catch and record.

---

### Task 1: Make the shared organization upsert safe without a NoteID

The spreadsheet has no `NoteID`. Today `_find_by_noteid(doctype, None)` runs `WHERE acumatica_noteid IS NULL` and returns *some* unrelated organization; `_adopt` then treats our `None` as a claim; and `doc.acumatica_noteid = None` would erase a NoteID a later live sync had written. Three guards.

**Files:**
- Modify: `crm/integrations/acumatica/importer.py:14-55`
- Test: `crm/integrations/acumatica/test_importer.py`

**Interfaces:**
- Produces: `upsert_organization(rec) -> str` now accepts a record with no `NoteID` and finds an existing organization by `CustomerID` → `acumatica_id`. Task 4 relies on this.

- [ ] **Step 1: Write the failing tests**

Append to `TestUpserts` in `crm/integrations/acumatica/test_importer.py`:

```python
	def test_a_record_without_noteid_never_adopts_a_stranger(self):
		# an unrelated org with no NoteID must not be returned by a NULL lookup
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Bystander Ltd"}).insert()
		name = importer.upsert_organization(C(CustomerID="C-NEW01", CustomerName="Newcomer Ltd"))
		self.assertEqual(name, "Newcomer Ltd")
		self.assertIsNone(frappe.db.get_value("CRM Organization", "Bystander Ltd", "acumatica_id"))

	def test_a_record_without_noteid_reuses_the_org_with_its_customer_id(self):
		first = importer.upsert_organization(C(CustomerID="C-REP01", CustomerName="Repeat Ltd"))
		second = importer.upsert_organization(C(CustomerID="C-REP01", CustomerName="Repeat Ltd"))
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("CRM Organization", {"acumatica_id": "C-REP01"}), 1)

	def test_a_record_without_noteid_does_not_erase_a_synced_noteid(self):
		importer.upsert_organization(C(NoteID="guid-keep", CustomerID="C-KEEP1", CustomerName="Keeper Ltd"))
		importer.upsert_organization(C(CustomerID="C-KEEP1", CustomerName="Keeper Ltd"))
		self.assertEqual(frappe.db.get_value("CRM Organization", "Keeper Ltd", "acumatica_noteid"), "guid-keep")
```

- [ ] **Step 2: Run them to verify they fail**

Run (in the devcontainer, from `/home/frappe/frappe-bench`):
`bench --site test_site run-tests --module crm.integrations.acumatica.test_importer`
Expected: the three new tests FAIL (first one adopts "Bystander Ltd" or errors; third loses the NoteID).

- [ ] **Step 3: Add the guards**

In `crm/integrations/acumatica/importer.py` replace `_find_by_noteid`, `_adopt` and `upsert_organization` with:

```python
def _find_by_noteid(doctype, noteid):
	if not noteid:
		# {"acumatica_noteid": None} is `IS NULL` -- it would return whichever record
		# happens to have no NoteID, which is every record a spreadsheet import wrote.
		return None
	return frappe.db.get_value(doctype, {"acumatica_noteid": noteid}, "name")


def _find_by_acumatica_id(doctype, acumatica_id):
	if not acumatica_id:
		return None
	return frappe.db.get_value(doctype, {"acumatica_id": acumatica_id}, "name")


def _adopt(doctype, name, noteid):
	"""Claim a pre-existing CRM record that matches an Acumatica record on its natural key.

	Without this, a customer that already exists in the CRM under the same name collides
	on save (CRM Organization/CRM Product autoname on the natural key) -- the record is
	never linked, so the outbound hook later PUTs a SECOND Customer into the client's ERP.

	A record already carrying a DIFFERENT NoteID is somebody else's: adopting it would
	steal the link, so raise instead and let the caller log a sync issue. A caller with
	no NoteID at all (the spreadsheet import) makes no claim and cannot steal one."""
	if not name:
		return None
	claimed = frappe.db.get_value(doctype, name, "acumatica_noteid")
	if claimed and noteid and claimed != noteid:
		raise ValueError(f"{doctype} {name} is already linked to Acumatica NoteID {claimed}")
	return name


def upsert_organization(rec) -> str:
	noteid = v(rec, "NoteID")
	customer_id = v(rec, "CustomerID")
	name = _find_by_noteid("CRM Organization", noteid)
	organization_name = v(rec, "CustomerName") or customer_id
	if not name:
		# The spreadsheet import has no NoteID, so the human-readable ID is its key;
		# a later live sync then finds the imported row here before it can create a rival.
		name = _adopt("CRM Organization", _find_by_acumatica_id("CRM Organization", customer_id), noteid)
	if not name and organization_name:
		# CRM Organization autonames on `field:organization_name`, so the docname IS the name.
		name = _adopt("CRM Organization", frappe.db.exists("CRM Organization", organization_name), noteid)
	doc = frappe.get_doc("CRM Organization", name) if name else frappe.new_doc("CRM Organization")
	doc.organization_name = organization_name
	if noteid:
		# never let a NoteID-less caller blank out a link the live sync wrote
		doc.acumatica_noteid = noteid
	doc.acumatica_id = customer_id
	currency = v(rec, "CurrencyID")
	if currency and frappe.db.exists("Currency", currency):
		doc.currency = currency
	doc.save(ignore_permissions=True)
	if name and doc.organization_name != organization_name:
		# CRM Organization autonames on `field:organization_name`; Document._sync_autoname_field()
		# re-derives the field FROM the (stable) docname on every save, clobbering an update to the
		# display name for an existing record. db_set writes it through without a rename.
		doc.db_set("organization_name", organization_name)
	return doc.name
```

- [ ] **Step 4: Run the whole importer module**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_importer`
Expected: PASS, including the pre-existing tests (NoteID matching is unchanged for callers that have one).

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/importer.py crm/integrations/acumatica/test_importer.py
git commit -m "fix: the organization upsert is safe for a record with no NoteID

_find_by_noteid(None) ran WHERE acumatica_noteid IS NULL and returned an
unrelated organization; _adopt treated None as a claim; and the save blanked
a NoteID a live sync had written. A spreadsheet import has no NoteID, so it
now keys on acumatica_id and makes no claim."
```

---

### Task 2: Pure transforms

Every function here is I/O-free and carries one of the spec's silent-corruption rules.

**Files:**
- Create: `crm/integrations/acumatica/spreadsheet.py`
- Create: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Produces (all pure):
  - `normalise_account_name(name: str) -> str`
  - `usable_email(value) -> str | None`
  - `normalise_phone(value) -> str | None`
  - `map_country(iso2, table: dict[str, str]) -> str | None` — `table` is `{lowercase_code: country_name}`
  - `to_decimal(value) -> Decimal`
  - `map_deal_status(status: str, outcome) -> str | None` — for `QT` rows only; `None` means "unknown, reject"
  - `within_window(quote_date: date, as_of: date, days: int) -> bool`
  - `OPEN_STATUS = "Proposal/Quotation"`, `PLACEHOLDER_EMAILS = {"no@email.co.za"}`

- [ ] **Step 1: Write the failing tests**

Create `crm/integrations/acumatica/test_spreadsheet.py`:

```python
"""Spreadsheet import tests.

The transforms are pure -- values in, values out -- so the corruption rules live
here without a site. The importers run against the test site further down,
against small workbooks the tests build themselves: the MBP files are the
client's data and are never committed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from frappe.tests import UnitTestCase

from crm.integrations.acumatica import spreadsheet as ss

COUNTRIES = {"za": "South Africa", "na": "Namibia", "mz": "Mozambique"}


class TransformTest(UnitTestCase):
	def test_only_the_cod_suffix_is_stripped(self):
		self.assertEqual(ss.normalise_account_name("2HK Trading (Pty) Ltd - COD"), "2HK Trading (Pty) Ltd")
		self.assertEqual(ss.normalise_account_name("ProProcess Fabrication - Cod"), "ProProcess Fabrication")
		for kept in (
			"Impala Platinum Limited - Shaft 10",
			"Sibanye Gold Ltd - Driefontein Division",
			"Nafasi Water - Mozambique",
			"Plain Name",
		):
			self.assertEqual(ss.normalise_account_name(kept), kept)

	def test_placeholder_and_list_emails_are_dropped(self):
		self.assertIsNone(ss.usable_email("no@email.co.za"))
		self.assertIsNone(ss.usable_email("a@x.co.za; statements@y.com"))
		self.assertIsNone(ss.usable_email(None))
		self.assertIsNone(ss.usable_email(""))
		self.assertEqual(ss.usable_email("  Katlego@yendelela.co.za "), "katlego@yendelela.co.za")

	def test_local_phones_become_e164(self):
		self.assertEqual(ss.normalise_phone("0792530729"), "+27792530729")
		self.assertEqual(ss.normalise_phone("011 849 1584"), "+27118491584")
		self.assertEqual(ss.normalise_phone("+27 79 253 0729"), "+27792530729")
		self.assertIsNone(ss.normalise_phone(None))
		self.assertIsNone(ss.normalise_phone("   "))
		# not a ten-digit local number: keep the digits, do not invent a country
		self.assertEqual(ss.normalise_phone("12345"), "12345")

	def test_country_codes_match_case_insensitively_and_na_is_namibia(self):
		self.assertEqual(ss.map_country("ZA", COUNTRIES), "South Africa")
		self.assertEqual(ss.map_country("na", COUNTRIES), "Namibia")
		self.assertIsNone(ss.map_country("XX", COUNTRIES))
		self.assertIsNone(ss.map_country(None, COUNTRIES))

	def test_money_goes_through_str_not_binary_float(self):
		self.assertEqual(ss.to_decimal(20359.6), Decimal("20359.6"))
		self.assertEqual(ss.to_decimal(0), Decimal("0"))
		self.assertEqual(ss.to_decimal(None), Decimal("0"))
		self.assertEqual(ss.to_decimal(Decimal("1.10")), Decimal("1.10"))

	def test_every_observed_quote_status_maps(self):
		cases = {
			("Open", None): ss.OPEN_STATUS,
			("Open", "Open"): ss.OPEN_STATUS,
			("On Hold", None): ss.OPEN_STATUS,
			("Pending Approval", None): ss.OPEN_STATUS,
			("Completed", None): "Won",
			("Open", "Lost"): "Lost",
			("Completed", "Lost"): "Lost",
			("Canceled", None): "Lost",
			("Rejected", None): "Lost",
		}
		for (status, outcome), expected in cases.items():
			self.assertEqual(ss.map_deal_status(status, outcome), expected, (status, outcome))
		self.assertIsNone(ss.map_deal_status("Shipping", None))  # unknown: caller rejects

	def test_window_boundary_is_inclusive_on_the_cutoff_day(self):
		as_of = date(2026, 9, 2)
		self.assertTrue(ss.within_window(date(2026, 6, 4), as_of, 90))  # exactly 90 days
		self.assertFalse(ss.within_window(date(2026, 6, 3), as_of, 90))  # 91 days
		self.assertTrue(ss.within_window(as_of, as_of, 0))
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `ModuleNotFoundError: crm.integrations.acumatica.spreadsheet`.

- [ ] **Step 3: Implement the transforms**

Create `crm/integrations/acumatica/spreadsheet.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: pure transforms for the MBP spreadsheet import

Name, email, phone, country, money, status and window rules as I/O-free
functions with direct tests -- these are the rules that corrupt silently."
```

---

### Task 3: Workbook reader and the reject/commit helpers

**Files:**
- Modify: `crm/integrations/acumatica/spreadsheet.py`
- Modify: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Produces:
  - `read_sheet(path, sheet="Data") -> list[dict]` — header-keyed rows, blank rows dropped, raises `ValueError` for anything but `.xlsx`
  - `Rejects` — `.add(file, key, reason)`, `.rows: list[dict]`, `len()`
  - `_commit_every(n: int)` — commits at every `COMMIT_EVERY` unless `frappe.flags.in_test`
  - `_country_table() -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

Append to `test_spreadsheet.py` (add `import tempfile`, `from pathlib import Path`, `from datetime import datetime`, and `from openpyxl import Workbook` at the top):

```python
def write_workbook(path: Path, header: list[str], rows: list[list]) -> Path:
	"""The exports have a `Data` sheet with a header row and a `Parameters` sheet."""
	wb = Workbook()
	ws = wb.active
	ws.title = "Data"
	ws.append(header)
	for row in rows:
		ws.append(row)
	wb.create_sheet("Parameters").append(["Title:", "test"])
	wb.save(path)
	return path


class ReaderTest(UnitTestCase):
	def setUp(self):
		self.dir = Path(tempfile.mkdtemp())

	def test_rows_are_keyed_by_header_and_dates_stay_datetimes(self):
		path = write_workbook(
			self.dir / "t.xlsx",
			["Customer ID", "Created On", "Credit Limit"],
			[["C-1", datetime(2025, 10, 20, 9, 53), 0], [None, None, None], ["C-2", datetime(2026, 1, 2), 1.5]],
		)
		rows = ss.read_sheet(path)
		self.assertEqual([r["Customer ID"] for r in rows], ["C-1", "C-2"])  # blank row dropped
		self.assertEqual(rows[0]["Created On"], datetime(2025, 10, 20, 9, 53))
		self.assertIsInstance(rows[1]["Credit Limit"], float)

	def test_csv_is_refused(self):
		with self.assertRaises(ValueError):
			ss.read_sheet(self.dir / "t.csv")


class RejectsTest(UnitTestCase):
	def test_rejects_are_kept_in_order_with_their_reason(self):
		rejects = ss.Rejects()
		rejects.add("sales_orders", "QT1", "unmapped salesperson 022")
		rejects.add("customers", "C-9", "no organization name")
		self.assertEqual(len(rejects), 2)
		self.assertEqual(rejects.rows[0], {"file": "sales_orders", "key": "QT1", "reason": "unmapped salesperson 022"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `AttributeError: module ... has no attribute 'read_sheet'`.

- [ ] **Step 3: Implement**

Add to `spreadsheet.py` (imports at top: `from pathlib import Path`, `import frappe`, `from openpyxl import load_workbook`, and `from crm.integrations.acumatica.importer import COMMIT_EVERY, upsert_organization`):

```python
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
		return [dict(zip(header, row)) for row in rows_iter if any(cell is not None for cell in row)]
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: workbook reader and reject list for the spreadsheet import"
```

---

### Task 4: Customers → organizations and addresses

**Files:**
- Modify: `crm/integrations/acumatica/spreadsheet.py`
- Modify: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Consumes: `upsert_organization(rec)` from Task 1 (a `{"value": x}`-wrapped record without `NoteID`).
- Produces:
  - `dedupe_customers(rows: list[dict]) -> list[dict]` (pure)
  - `shape_customer(row: dict) -> dict` (pure) → `{"rec": {...wrapped...}, "address": {...} | None, "customer_id", "status"}`
  - `upsert_address(organization: str, fields: dict) -> str`
  - `import_customers(path, rejects: Rejects) -> dict` → `{"organizations": n, "addresses": n, "skipped_inactive": n, "addresses_skipped": n}`

- [ ] **Step 1: Write the failing tests**

Append to `test_spreadsheet.py` (add `import frappe`, `from frappe.tests import IntegrationTestCase`, and `from crm.integrations.acumatica.install import ensure_custom_fields`):

```python
CUSTOMER_HEADER = [
	"Customer ID", "Customer Name", "Customer Class", "Address Line 1", "State", "City", "Postal Code",
	"Country", "Currency ID", "Customer Status", "Email", "Salesperson ID", "Sales Person", "Phone 1",
	"Default", "Created On", "Address Line 2",
]


def customer(**over):
	row = {
		"Customer ID": "C-2HK001",
		"Customer Name": "2HK Trading & Projects (Pty) Ltd - COD",
		"Customer Class": "COD",
		"Address Line 1": "5 Springbok Avenue",
		"State": "EC",
		"City": "Olifantsfontein - EC",
		"Postal Code": "1666",
		"Country": "ZA",
		"Currency ID": "ZAR",
		"Customer Status": "Active",
		"Email": "no@email.co.za",
		"Salesperson ID": "003",
		"Sales Person": "Simon Mofokeng",
		"Phone 1": "0792530729",
		"Default": "True",
		"Created On": datetime(2025, 10, 20, 9, 53, 43),
		"Address Line 2": "Clayville East",
	}
	row.update(over)
	return [row[h] for h in CUSTOMER_HEADER]


class DedupeTest(UnitTestCase):
	def test_duplicate_ids_keep_the_default_row(self):
		a = dict(zip(CUSTOMER_HEADER, customer(**{"Customer ID": "C-MET006", "Default": None, "Salesperson ID": None})))
		b = dict(zip(CUSTOMER_HEADER, customer(**{"Customer ID": "C-MET006", "Default": "True", "Salesperson ID": "030"})))
		out = ss.dedupe_customers([a, b])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["Salesperson ID"], "030")

	def test_identical_duplicates_collapse_to_one(self):
		a = dict(zip(CUSTOMER_HEADER, customer()))
		self.assertEqual(len(ss.dedupe_customers([a, dict(a)])), 1)


class SpreadsheetImportTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()  # acumatica_id / acumatica_sales_quote: absent on a fresh site

	def setUp(self):
		super().setUp()
		self.dir = Path(tempfile.mkdtemp())

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()


class ImportCustomersTest(SpreadsheetImportTestCase):
	def test_creates_organization_and_address_with_filtered_contact_details(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer()])
		rejects = ss.Rejects()
		counts = ss.import_customers(path, rejects)
		self.assertEqual(len(rejects), 0)
		self.assertEqual(counts["organizations"], 1)
		org = frappe.get_doc("CRM Organization", "2HK Trading & Projects (Pty) Ltd")  # COD stripped
		self.assertEqual(org.acumatica_id, "C-2HK001")
		self.assertEqual(org.currency, "ZAR")
		address = frappe.get_doc("Address", org.address)
		self.assertEqual(address.country, "South Africa")
		self.assertEqual(address.address_line2, "Clayville East")
		self.assertEqual(address.phone, "+27792530729")
		self.assertFalse(address.email_id)  # placeholder dropped
		self.assertEqual(address.links[0].link_name, org.name)

	def test_inactive_customers_are_skipped_and_on_hold_kept(self):
		path = write_workbook(
			self.dir / "customers.xlsx",
			CUSTOMER_HEADER,
			[
				customer(**{"Customer ID": "C-A", "Customer Name": "A Ltd", "Customer Status": "Inactive"}),
				customer(**{"Customer ID": "C-B", "Customer Name": "B Ltd", "Customer Status": "On Hold"}),
			],
		)
		counts = ss.import_customers(path, ss.Rejects())
		self.assertEqual(counts["skipped_inactive"], 1)
		self.assertFalse(frappe.db.exists("CRM Organization", "A Ltd"))
		self.assertTrue(frappe.db.exists("CRM Organization", "B Ltd"))

	def test_rerun_updates_in_place(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer()])
		ss.import_customers(path, ss.Rejects())
		ss.import_customers(path, ss.Rejects())
		self.assertEqual(frappe.db.count("CRM Organization", {"acumatica_id": "C-2HK001"}), 1)
		self.assertEqual(
			frappe.db.count("Dynamic Link", {"link_doctype": "CRM Organization", "link_name": "2HK Trading & Projects (Pty) Ltd", "parenttype": "Address"}),
			1,
		)

	def test_missing_street_or_city_skips_the_address_not_the_organization(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer(**{"City": None})])
		counts = ss.import_customers(path, ss.Rejects())
		self.assertEqual(counts["organizations"], 1)
		self.assertEqual(counts["addresses_skipped"], 1)
		self.assertFalse(frappe.db.get_value("CRM Organization", "2HK Trading & Projects (Pty) Ltd", "address"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `AttributeError ... 'dedupe_customers'`.

- [ ] **Step 3: Implement**

Add to `spreadsheet.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS. If `Address` complains that `country` is mandatory on the `City: None` case, the address was not skipped — check the `line1 and city` guard.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: import Customers as organizations and billing addresses

Dedupes on Customer ID, strips only the COD suffix, drops placeholder and
list emails, and keys the address on its link to the organization so a
re-run edits rather than duplicates."
```

---

### Task 5: Sales Orders → deals

The task with every controller trap. Read the *Global Constraints* bullets on `closed_date`, `lost_reason`, forecasting fields and currency before starting.

**Files:**
- Modify: `crm/integrations/acumatica/spreadsheet.py`
- Modify: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Consumes: `map_deal_status`, `within_window`, `to_decimal`, `Rejects`, `_commit_every`, `read_sheet`.
- Produces:
  - `LOST_REASON = "Not recorded in Acumatica"`
  - `shape_sales_order(row, *, as_of: date, window_days: int, quote_validity_days: int, owners: dict[str, str], default_owner: str | None, rates: dict[str, Decimal], base_currency: str) -> dict` (pure) → one of `{"skip": reason}`, `{"reject": reason, "key": nbr}`, or a deal dict with keys `order_nbr, customer_id, status, value, currency, exchange_rate, owner, quote_date, closed_date, expected_closure_date`
  - `upsert_deal(deal: dict, organization: str) -> str`
  - `import_sales_orders(path, rejects, *, owners, rates, window_days=90, quote_validity_days=30, default_owner=None, manifest: set[str] | None = None) -> dict` → `{"deals": n, "won": n, "lost": n, "open": n, "excluded": {...}, "outside_window": n, "skipped_deleted": n, "as_of": date}`

- [ ] **Step 1: Write the failing tests**

Append to `test_spreadsheet.py`:

```python
ORDER_HEADER = [
	"Order Type", "Order Nbr.", "Status", "Date", "Sched. Shipment", "Quote Outcome", "Created By",
	"Default Salesperson", "Customer", "Customer Name", "Ordered Qty.", "Order Total", "Currency",
	"Created On", "Est. Margin (%)",
]
AS_OF = date(2026, 9, 2)
OWNERS = {"018": "annmari@crmtest.test", "003": "simon@crmtest.test"}
RATES = {"USD": Decimal("18.2")}


def order(**over):
	row = {
		"Order Type": "QT",
		"Order Nbr.": "QT103012",
		"Status": "Open",
		"Date": datetime(2026, 9, 2),
		"Sched. Shipment": datetime(2026, 9, 2),
		"Quote Outcome": None,
		"Created By": "ReneO@mbpeng.co.za",
		"Default Salesperson": "018",
		"Customer": "C-PRO004",
		"Customer Name": "Proserve (Pty) Ltd",
		"Ordered Qty.": 30,
		"Order Total": 20359.6,
		"Currency": "ZAR",
		"Created On": datetime(2026, 9, 2, 13, 53),
		"Est. Margin (%)": 33.82,
	}
	row.update(over)
	return row


def shape(**over):
	return ss.shape_sales_order(
		order(**over),
		as_of=AS_OF,
		window_days=90,
		quote_validity_days=30,
		owners=OWNERS,
		default_owner=None,
		rates=RATES,
		base_currency="ZAR",
	)


class ShapeSalesOrderTest(UnitTestCase):
	def test_non_quote_rows_are_skipped_not_rejected(self):
		for order_type in ("SO", "TR", "CM"):
			self.assertIn("skip", shape(**{"Order Type": order_type}))

	def test_an_open_quote_becomes_an_open_deal_with_a_validity_close_date(self):
		deal = shape()
		self.assertEqual(deal["status"], ss.OPEN_STATUS)
		self.assertEqual(deal["value"], Decimal("20359.6"))
		self.assertEqual(deal["owner"], "annmari@crmtest.test")
		self.assertEqual(deal["expected_closure_date"], date(2026, 10, 2))
		self.assertIsNone(deal["closed_date"])
		self.assertEqual(deal["exchange_rate"], Decimal("1"))

	def test_a_completed_quote_is_won_on_its_own_date(self):
		deal = shape(**{"Status": "Completed", "Date": datetime(2026, 5, 1)})
		self.assertEqual(deal["status"], "Won")
		self.assertEqual(deal["closed_date"], date(2026, 5, 1))
		self.assertEqual(deal["expected_closure_date"], date(2026, 5, 1))

	def test_won_and_lost_ignore_the_window_but_open_does_not(self):
		old = {"Date": datetime(2026, 1, 15)}
		self.assertEqual(shape(**{"Status": "Completed", **old})["status"], "Won")
		self.assertEqual(shape(**{"Quote Outcome": "Lost", **old})["status"], "Lost")
		self.assertEqual(shape(**old), {"skip": "outside window"})

	def test_usd_rows_carry_their_rate_and_unknown_currencies_reject(self):
		self.assertEqual(shape(**{"Currency": "USD"})["exchange_rate"], Decimal("18.2"))
		self.assertIn("reject", shape(**{"Currency": "EUR"}))

	def test_unmapped_or_missing_salesperson_rejects_unless_a_default_is_given(self):
		self.assertEqual(shape(**{"Default Salesperson": "022"})["reject"], "unmapped salesperson 022")
		self.assertEqual(shape(**{"Default Salesperson": None})["reject"], "no salesperson")
		with_default = ss.shape_sales_order(
			order(**{"Default Salesperson": None}), as_of=AS_OF, window_days=90, quote_validity_days=30,
			owners=OWNERS, default_owner="manager@crmtest.test", rates=RATES, base_currency="ZAR",
		)
		self.assertEqual(with_default["owner"], "manager@crmtest.test")

	def test_an_unknown_status_rejects_with_the_values_seen(self):
		self.assertEqual(shape(**{"Status": "Shipping"})["reject"], "unknown quote status Shipping / None")


class ImportSalesOrdersTest(SpreadsheetImportTestCase):
	def setUp(self):
		super().setUp()
		for email, first in (("annmari@crmtest.test", "Ann-Mari"), ("simon@crmtest.test", "Simon")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc({"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0})
				user.insert(ignore_permissions=True)
				user.add_roles("Sales User")
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Proserve (Pty) Ltd", "acumatica_id": "C-PRO004"}).insert()

	def rows(self, *rows):
		return write_workbook(self.dir / "orders.xlsx", ORDER_HEADER, [[r[h] for h in ORDER_HEADER] for r in rows])

	def test_open_won_and_lost_land_with_real_dates_and_reasons(self):
		path = self.rows(
			order(),
			order(**{"Order Nbr.": "QT100001", "Status": "Completed", "Date": datetime(2026, 5, 1)}),
			order(**{"Order Nbr.": "QT100002", "Quote Outcome": "Lost", "Date": datetime(2026, 4, 1)}),
		)
		rejects = ss.Rejects()
		counts = ss.import_sales_orders(path, rejects, owners=OWNERS, rates=RATES)
		self.assertEqual(len(rejects), 0, rejects.rows)
		self.assertEqual((counts["open"], counts["won"], counts["lost"]), (1, 1, 1))
		won = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT100001"})
		self.assertEqual(won.status, "Won")
		self.assertEqual(str(won.closed_date), "2026-05-01")  # not today: validate() stamps today, we write it back
		self.assertEqual(won.deal_owner, "annmari@crmtest.test")
		self.assertEqual(won.organization, "Proserve (Pty) Ltd")
		lost = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT100002"})
		self.assertEqual(lost.lost_reason, ss.LOST_REASON)
		open_deal = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT103012"})
		self.assertEqual(str(open_deal.expected_closure_date), "2026-10-02")
		self.assertEqual(open_deal.expected_deal_value, open_deal.deal_value)

	def test_a_usd_deal_keeps_the_supplied_rate(self):
		path = self.rows(order(**{"Currency": "USD", "Order Total": 1000}))
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		deal = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT103012"})
		self.assertEqual(deal.currency, "USD")
		self.assertAlmostEqual(deal.exchange_rate, 18.2)

	def test_rerun_updates_and_never_duplicates(self):
		path = self.rows(order())
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		path = self.rows(order(**{"Order Total": 999}))
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		self.assertEqual(frappe.db.count("CRM Deal", {"acumatica_sales_quote": "QT103012"}), 1)
		self.assertEqual(frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": "QT103012"}, "deal_value"), 999)

	def test_a_deal_in_the_manifest_but_gone_from_the_site_is_not_resurrected(self):
		path = self.rows(order())
		manifest = {"QT103012"}  # created by an earlier run, then deleted by a rep
		counts = ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES, manifest=manifest)
		self.assertEqual(counts["skipped_deleted"], 1)
		self.assertFalse(frappe.db.exists("CRM Deal", {"acumatica_sales_quote": "QT103012"}))

	def test_a_missing_organization_rejects_the_row(self):
		path = self.rows(order(**{"Customer": "C-NOPE"}))
		rejects = ss.Rejects()
		ss.import_sales_orders(path, rejects, owners=OWNERS, rates=RATES)
		self.assertEqual(rejects.rows[0]["reason"], "customer C-NOPE has no organization on the site")
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `AttributeError ... 'shape_sales_order'`.

- [ ] **Step 3: Implement**

Add to `spreadsheet.py`:

```python
LOST_REASON = "Not recorded in Acumatica"


def _ensure_lost_reason() -> None:
	# validate_lost_reason() refuses a Lost deal without one; the file never says why
	if not frappe.db.exists("CRM Lost Reason", LOST_REASON):
		frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": LOST_REASON}).insert(ignore_permissions=True)


def shape_sales_order(
	row: dict,
	*,
	as_of: date,
	window_days: int,
	quote_validity_days: int,
	owners: dict[str, str],
	default_owner: str | None,
	rates: dict[str, Decimal],
	base_currency: str,
) -> dict:
	"""One export row -> a deal, a skip, or a reject. Pure: every decision the spec
	argues about is visible here and nowhere else."""
	nbr = row.get("Order Nbr.")
	order_type = row.get("Order Type")
	if order_type != "QT":
		# fulfilment records, branch transfers and credit memos are not opportunities
		return {"skip": f"order type {order_type}"}

	status = map_deal_status(row.get("Status"), row.get("Quote Outcome"))
	if status is None:
		return {"reject": f"unknown quote status {row.get('Status')} / {row.get('Quote Outcome')}", "key": nbr}

	quote_date = row["Date"].date() if hasattr(row.get("Date"), "date") else row.get("Date")
	if not quote_date:
		return {"reject": "no date", "key": nbr}
	if status == OPEN_STATUS and not within_window(quote_date, as_of, window_days):
		return {"skip": "outside window"}

	code = row.get("Default Salesperson")
	if code:
		owner = owners.get(str(code).strip())
		if not owner:
			return {"reject": f"unmapped salesperson {code}", "key": nbr}
	elif default_owner:
		owner = default_owner
	else:
		return {"reject": "no salesperson", "key": nbr}

	currency = row.get("Currency") or base_currency
	if currency == base_currency:
		rate = Decimal("1")
	elif currency in rates:
		rate = Decimal(str(rates[currency]))
	else:
		return {"reject": f"no exchange rate supplied for {currency}", "key": nbr}

	closed = status in ("Won", "Lost")
	return {
		"order_nbr": nbr,
		"customer_id": row.get("Customer"),
		"status": status,
		"value": to_decimal(row.get("Order Total")),
		"currency": currency,
		"exchange_rate": rate,
		"owner": owner,
		"quote_date": quote_date,
		"closed_date": quote_date if closed else None,
		# a closed quote closed on its date; an open one is assumed good for its validity
		"expected_closure_date": quote_date if closed else quote_date + timedelta(days=quote_validity_days),
	}


def upsert_deal(deal: dict, organization: str) -> str:
	name = frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": deal["order_nbr"]}, "name")
	doc = frappe.get_doc("CRM Deal", name) if name else frappe.new_doc("CRM Deal")
	doc.organization = organization
	doc.status = deal["status"]
	doc.deal_value = float(deal["value"])
	# validate_forecasting_fields() throws without these when forecasting is on
	doc.expected_deal_value = float(deal["value"])
	doc.expected_closure_date = deal["expected_closure_date"]
	doc.currency = deal["currency"]
	doc.exchange_rate = float(deal["exchange_rate"])
	doc.deal_owner = deal["owner"]
	doc.acumatica_sales_quote = deal["order_nbr"]
	doc.acumatica_customer = deal["customer_id"]
	if deal["status"] == "Lost":
		doc.lost_reason = LOST_REASON
	doc.save(ignore_permissions=True)

	after = {}
	if deal["closed_date"]:
		# validate() stamps closed_date = today on any transition into Won; the file
		# knows the real date, so write it through after the controller has run
		after["closed_date"] = deal["closed_date"]
	if deal["exchange_rate"] != 1:
		# update_exchange_rate() tries a live fetch for a non-base currency on insert
		# and may have replaced the supplied rate; the supplied rate is the record
		after["exchange_rate"] = float(deal["exchange_rate"])
	if after:
		doc.db_set(after, update_modified=False)
	return doc.name


def import_sales_orders(
	path,
	rejects: Rejects,
	*,
	owners: dict[str, str],
	rates: dict[str, Decimal] | None = None,
	window_days: int = 90,
	quote_validity_days: int = 30,
	default_owner: str | None = None,
	manifest: set[str] | None = None,
) -> dict:
	"""``manifest`` is the set of order numbers an earlier run created. One of those
	with no deal on the site was deleted by a rep, and a re-run must not bring it back."""
	rows = read_sheet(path)
	if not rows:
		return {"deals": 0, "as_of": None}
	as_of = max(r["Date"] for r in rows if r.get("Date")).date()
	base_currency = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
	rates = {k: Decimal(str(v)) for k, v in (rates or {}).items()}
	manifest = manifest if manifest is not None else set()
	_ensure_lost_reason()

	counts = {
		"deals": 0, "won": 0, "lost": 0, "open": 0, "outside_window": 0, "skipped_deleted": 0,
		"excluded": {}, "as_of": as_of,
	}
	for owner in set(owners.values()) | ({default_owner} if default_owner else set()):
		if not frappe.db.exists("User", owner):
			raise ValueError(f"owner {owner} is not a User on this site; create the users first")

	for done, row in enumerate(rows, 1):
		deal = shape_sales_order(
			row, as_of=as_of, window_days=window_days, quote_validity_days=quote_validity_days,
			owners=owners, default_owner=default_owner, rates=rates, base_currency=base_currency,
		)
		if "skip" in deal:
			if deal["skip"] == "outside window":
				counts["outside_window"] += 1
			else:
				counts["excluded"][deal["skip"]] = counts["excluded"].get(deal["skip"], 0) + 1
			continue
		if "reject" in deal:
			rejects.add("sales_orders", deal["key"], deal["reject"])
			continue
		nbr = deal["order_nbr"]
		if nbr in manifest and not frappe.db.exists("CRM Deal", {"acumatica_sales_quote": nbr}):
			counts["skipped_deleted"] += 1
			continue

		frappe.db.savepoint("ss_deal")
		try:
			organization = frappe.db.get_value("CRM Organization", {"acumatica_id": deal["customer_id"]}, "name")
			if not organization:
				raise ValueError(f"customer {deal['customer_id']} has no organization on the site")
			upsert_deal(deal, organization)
			manifest.add(nbr)
			counts["deals"] += 1
			counts[{"Won": "won", "Lost": "lost"}.get(deal["status"], "open")] += 1
		except Exception as e:
			frappe.db.rollback(save_point="ss_deal")
			rejects.add("sales_orders", nbr, str(e))
		_commit_every(done)
	return counts
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS. Two likely failures and their causes: `closed_date` equals today → the `db_set` after save did not run or the test read a cached doc (use `frappe.get_doc`, not a cached value); `Please specify a reason for losing the deal` → `_ensure_lost_reason()` did not run before the loop.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: import quotes as deals, keyed on the Acumatica order number

Open quotes within the window land in Proposal/Quotation with a validity
close date; Completed is Won on its own date, written after validate()
has stamped today; Lost carries a placeholder reason the controller
demands. USD rows keep the supplied rate. A manifest stops a re-run
resurrecting a deal a rep deleted."
```

---

### Task 6: Invoices → per-organization revenue

**Files:**
- Modify: `crm/integrations/acumatica/spreadsheet.py`
- Modify: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Produces:
  - `revenue_by_customer(rows: list[dict], rates: dict[str, Decimal], base_currency: str) -> tuple[dict[str, Decimal], list[tuple]]` (pure) — totals in base currency, and `(key, reason)` rejects
  - `import_invoices(path, rejects, *, rates) -> dict` → `{"organizations": n, "total": Decimal}`

- [ ] **Step 1: Write the failing tests**

Append to `test_spreadsheet.py`:

```python
INVOICE_HEADER = [
	"Type", "Reference Nbr.", "Status", "Date", "Post Period", "Customer", "Customer Name",
	"Description", "Customer Order Nbr.", "Amount", "Currency", "Created On",
]


def invoice(**over):
	row = {
		"Type": "Invoice", "Reference Nbr.": "IN-JHB1001418", "Status": "Open", "Date": datetime(2026, 9, 2),
		"Post Period": "04-2026", "Customer": "C-SURE01", "Customer Name": "Sure Seal SA (Pty) Ltd",
		"Description": "Ball vlv", "Customer Order Nbr.": "11520", "Amount": 430.39, "Currency": "ZAR",
		"Created On": datetime(2026, 9, 2, 10, 10),
	}
	row.update(over)
	return row


class RevenueTest(UnitTestCase):
	def test_credit_memos_subtract_cancelled_rows_are_ignored_and_usd_converts(self):
		rows = [
			invoice(),
			invoice(**{"Type": "Credit Memo", "Amount": 30.39}),
			invoice(**{"Status": "Canceled", "Amount": 1_000_000}),
			invoice(**{"Currency": "USD", "Amount": 10}),
		]
		totals, rejects = ss.revenue_by_customer(rows, RATES, "ZAR")
		self.assertEqual(totals["C-SURE01"], Decimal("400") + Decimal("182"))
		self.assertEqual(rejects, [])

	def test_an_unknown_currency_rejects_that_row_only(self):
		totals, rejects = ss.revenue_by_customer([invoice(), invoice(**{"Currency": "EUR"})], RATES, "ZAR")
		self.assertEqual(totals["C-SURE01"], Decimal("430.39"))
		self.assertEqual(rejects, [("IN-JHB1001418", "no exchange rate supplied for EUR")])


class ImportInvoicesTest(SpreadsheetImportTestCase):
	def test_writes_annual_revenue_on_the_organization(self):
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Sure Seal SA (Pty) Ltd", "acumatica_id": "C-SURE01"}).insert()
		path = write_workbook(self.dir / "inv.xlsx", INVOICE_HEADER, [[invoice()[h] for h in INVOICE_HEADER]])
		rejects = ss.Rejects()
		counts = ss.import_invoices(path, rejects, rates=RATES)
		self.assertEqual(len(rejects), 0)
		self.assertEqual(counts["organizations"], 1)
		self.assertAlmostEqual(frappe.db.get_value("CRM Organization", "Sure Seal SA (Pty) Ltd", "annual_revenue"), 430.39)

	def test_a_customer_with_no_organization_rejects(self):
		path = write_workbook(self.dir / "inv.xlsx", INVOICE_HEADER, [[invoice()[h] for h in INVOICE_HEADER]])
		rejects = ss.Rejects()
		ss.import_invoices(path, rejects, rates=RATES)
		self.assertEqual(rejects.rows[0]["key"], "C-SURE01")
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `AttributeError ... 'revenue_by_customer'`.

- [ ] **Step 3: Implement**

Add to `spreadsheet.py` (add `from collections import defaultdict` at the top):

```python
def revenue_by_customer(rows: list[dict], rates: dict[str, Decimal], base_currency: str):
	"""Invoice amounts summed per customer in the base currency. Credit memos are
	positive in the export and must be subtracted; cancelled rows are not revenue."""
	totals: dict[str, Decimal] = defaultdict(Decimal)
	rejects: list[tuple] = []
	for row in rows:
		if row.get("Status") == "Canceled":
			continue
		currency = row.get("Currency") or base_currency
		if currency == base_currency:
			rate = Decimal("1")
		elif currency in rates:
			rate = Decimal(str(rates[currency]))
		else:
			rejects.append((row.get("Reference Nbr."), f"no exchange rate supplied for {currency}"))
			continue
		amount = to_decimal(row.get("Amount")) * rate
		if row.get("Type") == "Credit Memo":
			amount = -amount
		totals[row.get("Customer")] += amount
	return dict(totals), rejects


def import_invoices(path, rejects: Rejects, *, rates: dict | None = None) -> dict:
	base_currency = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
	rates = {k: Decimal(str(v)) for k, v in (rates or {}).items()}
	totals, row_rejects = revenue_by_customer(read_sheet(path), rates, base_currency)
	for key, reason in row_rejects:
		rejects.add("invoices", key, reason)
	counts = {"organizations": 0, "total": Decimal("0")}
	for done, (customer_id, total) in enumerate(totals.items(), 1):
		organization = frappe.db.get_value("CRM Organization", {"acumatica_id": customer_id}, "name")
		if not organization:
			rejects.add("invoices", customer_id, f"customer {customer_id} has no organization on the site")
			continue
		# The window is nine months, not twelve. The field is named annual_revenue;
		# the rollout walk-through with MBP says what period it covers.
		frappe.db.set_value("CRM Organization", organization, "annual_revenue", float(total), update_modified=False)
		counts["organizations"] += 1
		counts["total"] += total
		_commit_every(done)
	return counts
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: derive organization revenue from Invoices, net of credit memos"
```

---

### Task 7: The entry point — pre-flight, dry-run, manifest, reject report

**Files:**
- Modify: `crm/integrations/acumatica/spreadsheet.py`
- Modify: `crm/integrations/acumatica/test_spreadsheet.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `import_workbooks(customers, sales_orders, invoices, owners, rates=None, window_days=90, quote_validity_days=30, default_owner=None, dry_run=False) -> dict` — callable via `bench execute`. `owners` is a path to a JSON file `{"018": "email", ...}` or a dict. Writes `import-manifest.json` and `import-rejects.json` next to the Sales Orders workbook (not on dry-run).

- [ ] **Step 1: Write the failing tests**

Append to `test_spreadsheet.py` (add `import json`):

```python
class ImportWorkbooksTest(SpreadsheetImportTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", "annmari@crmtest.test"):
			user = frappe.get_doc({"doctype": "User", "email": "annmari@crmtest.test", "first_name": "Ann-Mari", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("Sales User")
		self.customers = write_workbook(self.dir / "Customers.xlsx", CUSTOMER_HEADER, [customer(**{"Customer ID": "C-PRO004", "Customer Name": "Proserve (Pty) Ltd"})])
		self.orders = write_workbook(self.dir / "Sales Orders.xlsx", ORDER_HEADER, [[order()[h] for h in ORDER_HEADER]])
		self.invoices = write_workbook(self.dir / "Invoices.xlsx", INVOICE_HEADER, [[invoice(**{"Customer": "C-PRO004"})[h] for h in INVOICE_HEADER]])
		self.owners = self.dir / "owners.json"
		self.owners.write_text(json.dumps(OWNERS))
		frappe.db.set_single_value("FCRM Settings", "currency", "ZAR")

	def test_refuses_to_run_unless_the_base_currency_is_zar(self):
		frappe.db.set_single_value("FCRM Settings", "currency", "USD")
		with self.assertRaisesRegex(ValueError, "base currency"):
			ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})

	def test_dry_run_writes_nothing_and_still_reports(self):
		summary = ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}, dry_run=True)
		self.assertEqual(summary["customers"]["organizations"], 1)
		self.assertEqual(summary["sales_orders"]["deals"], 1)
		self.assertTrue(summary["dry_run"])
		self.assertFalse(frappe.db.exists("CRM Organization", "Proserve (Pty) Ltd"))
		self.assertFalse((self.dir / "import-manifest.json").exists())

	def test_a_real_run_writes_the_manifest_and_reject_report(self):
		summary = ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})
		self.assertTrue(frappe.db.exists("CRM Deal", {"acumatica_sales_quote": "QT103012"}))
		self.assertEqual(json.loads((self.dir / "import-manifest.json").read_text())["deals"], ["QT103012"])
		self.assertEqual(json.loads((self.dir / "import-rejects.json").read_text()), [])
		self.assertEqual(summary["warnings"], [])

	def test_the_manifest_is_read_back_on_the_next_run(self):
		ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})
		frappe.delete_doc("CRM Deal", frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": "QT103012"}, "name"), force=True)
		summary = ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})
		self.assertEqual(summary["sales_orders"]["skipped_deleted"], 1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: FAIL — `AttributeError ... 'import_workbooks'`.

- [ ] **Step 3: Implement**

Add to `spreadsheet.py` (add `import json`):

```python
def _load_owners(owners) -> dict[str, str]:
	if isinstance(owners, dict):
		return {str(k): v for k, v in owners.items()}
	return {str(k): v for k, v in json.loads(Path(owners).read_text()).items()}


def _manifest_path(sales_orders) -> Path:
	return Path(sales_orders).with_name("import-manifest.json")


def _read_manifest(path: Path) -> set[str]:
	if not path.exists():
		return set()
	return set(json.loads(path.read_text()).get("deals", []))


def import_workbooks(
	customers,
	sales_orders,
	invoices,
	owners,
	rates: dict | None = None,
	window_days: int = 90,
	quote_validity_days: int = 30,
	default_owner: str | None = None,
	dry_run: bool = False,
) -> dict:
	"""Entry point for ``bench --site <site> execute
	crm.integrations.acumatica.spreadsheet.import_workbooks --kwargs '{...}'``.

	Order is forced: organizations first (deals link to them), then deals, then
	revenue. A dry run does all the work inside the transaction and rolls it back,
	so the reject report is real. Everything else is re-runnable."""
	base_currency = frappe.db.get_single_value("FCRM Settings", "currency")
	if base_currency != "ZAR":
		# the deal controller fetches a live rate for anything not in the base
		# currency, so with the wrong base every ZAR row would hit the network
		raise ValueError(f"base currency is {base_currency!r}; set FCRM Settings.currency to ZAR before importing")
	dry = dry_run
	owners_map = _load_owners(owners)
	rejects = Rejects()
	manifest_path = _manifest_path(sales_orders)
	manifest = _read_manifest(manifest_path)
	warnings: list[str] = []

	summary = {"dry_run": dry, "warnings": warnings}
	try:
		summary["customers"] = import_customers(customers, rejects)
		summary["sales_orders"] = import_sales_orders(
			sales_orders, rejects, owners=owners_map, rates=rates, window_days=window_days,
			quote_validity_days=quote_validity_days, default_owner=default_owner, manifest=manifest,
		)
		summary["invoices"] = import_invoices(invoices, rejects, rates=rates)

		with_sla = frappe.db.count("CRM Deal", {"acumatica_sales_quote": ("is", "set"), "sla": ("is", "set")})
		if with_sla:
			warnings.append(f"{with_sla} imported deals picked up a Service Level Agreement; response timers are now running on them")
	finally:
		if dry:
			frappe.db.rollback()
		elif not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit

	summary["rejects"] = len(rejects)
	if not dry:
		manifest_path.write_text(json.dumps({"deals": sorted(manifest)}, indent=1))
		manifest_path.with_name("import-rejects.json").write_text(json.dumps(rejects.rows, indent=1))
	summary["reject_rows"] = rejects.rows
	# bench execute prints the return value; make the numbers readable
	for section in ("customers", "sales_orders", "invoices"):
		for key, value in list(summary.get(section, {}).items()):
			if isinstance(value, (Decimal, date)):
				summary[section][key] = str(value)
	return summary
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet`
Expected: PASS. Note the dry-run test: under test the rollback inside `import_workbooks` also rolls back the setUp fixtures — that is fine because the assertion is that nothing exists.

- [ ] **Step 5: Run the full acumatica test set and ruff**

Run:
```
bench --site test_site run-tests --module crm.integrations.acumatica.test_spreadsheet
bench --site test_site run-tests --module crm.integrations.acumatica.test_importer
cd /workspace && ruff check crm/integrations/acumatica/ && ruff format --check crm/integrations/acumatica/
```
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add crm/integrations/acumatica/spreadsheet.py crm/integrations/acumatica/test_spreadsheet.py
git commit -m "feat: bench-execute entry point for the MBP spreadsheet import

Pre-flight on the base currency, dry-run that does the work and rolls it
back so the reject report is real, a manifest of created deal keys, and a
warning if any imported deal picked up an SLA."
```

---

### Task 8: Document the runbook

**Files:**
- Modify: `.pi/feats/acumatica/README.md`

- [ ] **Step 1: Add a section**

Append to `.pi/feats/acumatica/README.md`:

````markdown
## Spreadsheet import (one-way, integration off)

`crm/integrations/acumatica/spreadsheet.py` loads Acumatica's Excel exports
without enabling the integration. Design and every mapping decision:
`docs/superpowers/specs/2026-09-03-mbp-acumatica-import-design.md`.

**Do not enable CRM Acumatica Settings to get the custom fields** — see the
spec's Prerequisite 1 and issue #166. Call the function directly:

```
bench --site <site> execute crm.integrations.acumatica.install.ensure_custom_fields
```

Put the workbooks and an `owners.json` (`{"018": "rep@example.com", ...}`)
under the site's private files, then dry-run:

```
bench --site <site> execute crm.integrations.acumatica.spreadsheet.import_workbooks --kwargs '{
  "customers": "sites/<site>/private/files/mbp/Customers 20260902.xlsx",
  "sales_orders": "sites/<site>/private/files/mbp/Sales Orders 20260902.xlsx",
  "invoices": "sites/<site>/private/files/mbp/Invoices 20260902.xlsx",
  "owners": "sites/<site>/private/files/mbp/owners.json",
  "rates": {"USD": 18.2},
  "window_days": 90,
  "quote_validity_days": 30,
  "dry_run": true
}'
```

Read the reject rows in the output. When they are all expected, run again
with `"dry_run": false`. Re-running is safe: organizations key on
`acumatica_id`, deals on `acumatica_sales_quote`, and `import-manifest.json`
next to the Sales Orders file stops a re-run resurrecting a deal a rep
deleted. Purchase Orders are not imported (no customer link).

Preconditions, in order: custom fields exist; the owner users exist;
`FCRM Settings.currency` is ZAR; a manual `bench backup --with-files`;
`clear_demo_data()` has run.
````

- [ ] **Step 2: Commit**

```bash
git add .pi/feats/acumatica/README.md
git commit -m "docs: runbook for the spreadsheet import"
```

---

## Self-review

**Spec coverage.** Global transform rules → Task 2 (`normalise_account_name`, `usable_email`, `normalise_phone`, `map_country`, `to_decimal`) and Task 3 (`.xlsx` only). File 1 mapping incl. Active/On Hold filter, dedupe, address on Dynamic Link → Task 4. File 2 mapping incl. status table, window, validity offset, USD, owner mapping, rejects for unknown status → Task 5. File 3 net of credit memos, USD converted → Task 6. Idempotency incl. manifest → Tasks 4, 5, 7. Prerequisite 1 (direct `ensure_custom_fields`) → Task 8 runbook. Dry-run + reject report → Task 7. `NoteID` note → Task 1. Testing section's named cases → Tasks 2, 5. **Not covered by design:** the candidate salesperson table is an input (`owners.json`), not code; territory is dropped; Purchase Orders excluded.

**Placeholder scan.** None. Every step has code or an exact command.

**Type consistency.** `Rejects.add(file, key, reason)` used identically in Tasks 4–7. `shape_sales_order` keyword signature matches its two callers (test `shape()` and `import_sales_orders`). `rates` is normalised to `Decimal` inside both importers, so `import_workbooks` may pass floats through. `import_sales_orders` returns `as_of` as a `date`, stringified only in `import_workbooks`.
