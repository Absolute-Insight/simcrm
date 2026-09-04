from datetime import datetime, timezone

import frappe

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_settings,
	record_sync_issue,
)
from crm.integrations.acumatica.client import AcumaticaClient, v

COMMIT_EVERY = 50  # keep transactions short; a 50k-customer backfill must not hold one tx


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


def _find_matching_contact(first, last, company_name, email):
	"""Contact autonames on first/last/company and appends "-1" on collision, so an
	unmatched import duplicates a person the CRM already knows ("Ana Diaz-1")."""
	filters = {"first_name": first, "last_name": last or ""}
	if company_name:
		filters["company_name"] = company_name
	name = frappe.db.get_value("Contact", filters, "name")
	if name:
		return name
	if email:
		return frappe.db.get_value(
			"Contact Email", {"email_id": email, "is_primary": 1, "parenttype": "Contact"}, "parent"
		)
	return None


def upsert_contact(rec) -> str | None:
	first = v(rec, "FirstName") or v(rec, "DisplayName")
	if not first:
		return None
	noteid = v(rec, "NoteID")
	last = v(rec, "LastName") or ""
	email = v(rec, "Email")

	company_name = None
	account = v(rec, "BusinessAccount")
	if account:
		company_name = frappe.db.get_value("CRM Organization", {"acumatica_id": account}, "name")

	name = _find_by_noteid("Contact", noteid)
	if not name:
		name = _adopt("Contact", _find_matching_contact(first, last, company_name, email), noteid)
	doc = frappe.get_doc("Contact", name) if name else frappe.new_doc("Contact")
	doc.first_name = first
	doc.last_name = last
	doc.acumatica_noteid = noteid
	doc.acumatica_id = v(rec, "ContactID")

	if email and not any(row.email_id == email for row in doc.email_ids):
		doc.append("email_ids", {"email_id": email, "is_primary": not doc.email_ids})
	phone = v(rec, "Phone1")
	if phone and not any(row.phone == phone for row in doc.phone_nos):
		doc.append("phone_nos", {"phone": phone})

	if company_name:
		doc.company_name = company_name
	doc.save(ignore_permissions=True)
	return doc.name


def upsert_product(rec) -> str:
	noteid = v(rec, "NoteID")
	product_code = v(rec, "InventoryID")
	name = _find_by_noteid("CRM Product", noteid)
	if not name and product_code:
		# CRM Product autonames on `field:product_code`, so the docname IS the InventoryID.
		name = _adopt("CRM Product", frappe.db.exists("CRM Product", product_code), noteid)
	doc = frappe.get_doc("CRM Product", name) if name else frappe.new_doc("CRM Product")
	doc.product_code = product_code
	doc.product_name = v(rec, "Description") or product_code
	doc.standard_rate = v(rec, "DefaultPrice") or 0
	doc.acumatica_noteid = noteid
	doc.acumatica_id = product_code
	doc.save(ignore_permissions=True)
	if name and doc.product_code != product_code:
		# Same autoname trap as CRM Organization above: _sync_autoname_field() re-derives
		# product_code from the docname on save, so an InventoryID rename in Acumatica
		# would silently revert here. db_set writes it through without a rename.
		doc.db_set("product_code", product_code)
	return doc.name


_ENTITIES = (
	# (entity, upsert fn key, result counter) -- customers first so contacts can link
	("Customer", upsert_organization, "customers"),
	("Contact", upsert_contact, "contacts"),
	("StockItem", upsert_product, "products"),
)


def run_backfill(modified_since: str | None = None) -> dict:
	"""Import everything (or everything modified since the high-water mark).
	Records that fail land in the sync-issues table instead of aborting the run."""
	settings = get_settings()
	client = AcumaticaClient(settings)
	counts = {"customers": 0, "contacts": 0, "products": 0, "issues": 0}
	filter_ = None
	if modified_since:
		# OData v3 literal. modified_since (from last_synced_at) is stored as naive
		# UTC, so the trailing Z is valid -- Acumatica interprets it as UTC too.
		filter_ = f"LastModifiedDateTime gt datetimeoffset'{modified_since}Z'"

	# now_datetime() returns naive SITE-LOCAL time -- storing that as the high-water
	# mark and asserting "Z" (UTC) on it would silently drop records on any site not
	# on UTC (e.g. skip everything modified in the site's UTC offset each sweep).
	# Capture naive UTC instead so the stored mark and the "Z" filter agree.
	started_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
	for entity, upsert, counter in _ENTITIES:
		done_in_entity = 0
		for rec in client.iter_all(entity, filter=filter_):
			# One savepoint per record: a failing upsert can leave half a document
			# written, and without the rollback that half rides along in the same
			# transaction as every good record until the next commit -- or aborts
			# the transaction outright, which took the whole page with it.
			frappe.db.savepoint("acumatica_rec")
			try:
				if not v(rec, "NoteID"):
					raise ValueError("record has no NoteID")
				if upsert(rec) is not None:
					counts[counter] += 1
			except Exception as e:
				frappe.db.rollback(save_point="acumatica_rec")
				counts["issues"] += 1
				try:
					record_sync_issue(
						entity,
						v(rec, "CustomerID") or v(rec, "InventoryID") or v(rec, "ContactID") or "?",
						"Import Failed",
						str(e),
					)
				except Exception:
					# record_sync_issue does its own doc.save() and can fail in turn;
					# losing the ability to log one bad record must not abort the rest
					# of the run.
					frappe.log_error(frappe.get_traceback(), "Acumatica sync issue recording failed")
			done_in_entity += 1
			if done_in_entity % COMMIT_EVERY == 0:
				# A 50k-record backfill must not hold one transaction; committing per
				# page keeps locks short and preserves progress if the job dies.
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
		# Entity boundary: same reasoning as the per-page commit above.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	# High-water mark is when this run STARTED: anything modified mid-run is
	# picked up again next sweep rather than lost in the gap.
	frappe.db.set_single_value("CRM Acumatica Settings", "last_synced_at", started_at)
	# The high-water mark must be durable the moment it is set -- the next sweep
	# reads it from a different worker process.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return counts


def nightly_sweep() -> None:
	"""Scheduler entry. Webhooks are the latency mechanism; this is the
	correctness mechanism -- Acumatica keeps failed push notifications for
	only 2 days, so the sweep must always run."""
	settings = get_settings()
	if not settings.enabled:
		return
	since = settings.last_synced_at
	run_backfill(modified_since=str(since).replace(" ", "T") if since else None)
