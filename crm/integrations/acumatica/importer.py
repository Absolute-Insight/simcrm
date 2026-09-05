import time
from datetime import datetime, timezone

import frappe
from frappe.utils.synchronization import LockTimeoutError, filelock

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_pending_retries,
	get_settings,
	record_sync_issue,
	set_pending_retries,
)
from crm.integrations.acumatica.client import AcumaticaClient, v
from crm.integrations.acumatica.names import normalise_account_name

COMMIT_EVERY = 50  # keep transactions short; a 50k-customer backfill must not hold one tx

# One name for the whole sync. Three things start it -- the manual backfill button,
# every webhook notification and the nightly scheduler -- and enqueueing all of them
# under this one job id lets `deduplicate` collapse them, queued or already running.
# That is best effort, not a guarantee: the dedup key is a redis entry with a TTL of
# its own, and `bench execute` reaches run_backfill without any queue at all. So
# run_backfill takes a site filelock of the same name, which is the thing that
# actually keeps two importers off the same pages.
SYNC_JOB_ID = "acumatica_sync"

# The long queue's default job timeout is 1500s. A first backfill of a real tenant
# (tens of thousands of customers, paced by request_pause) does not finish inside
# that, and run_backfill only writes last_synced_at once every entity is done -- so a
# killed run leaves no forward progress at all. Give it a working day's ceiling.
BACKFILL_TIMEOUT = 4 * 3600

# Retries are free (one filtered read each) but not infinite: a record that is still
# failing after five sweeps is failing on something no amount of waiting fixes, and
# an admin is better told about it than left with a queue that never drains.
MAX_RETRY_ATTEMPTS = 5


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
	organization_name = normalise_account_name(v(rec, "CustomerName") or customer_id or "")
	if not name:
		# The spreadsheet import has no NoteID, so the human-readable ID is its key;
		# a later live sync then finds the imported row here before it can create a rival.
		name = _adopt("CRM Organization", _find_by_acumatica_id("CRM Organization", customer_id), noteid)
	if not name and organization_name:
		# CRM Organization autonames on `field:organization_name`, so the docname IS the name.
		existing = frappe.db.exists("CRM Organization", organization_name)
		if existing and customer_id:
			other = frappe.db.get_value("CRM Organization", existing, "acumatica_id")
			if other and other != customer_id:
				# a differently-linked customer already holds this exact name -- adopting it
				# would silently merge two Acumatica customers into one CRM Organization
				raise ValueError(f"CRM Organization {existing} already belongs to Acumatica customer {other}")
		name = _adopt("CRM Organization", existing, noteid)
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


def _remote_id(rec) -> str:
	"""The id an admin can paste into Acumatica's search. Each entity spells it
	differently, and the NoteID an issue row would otherwise carry is a guid nobody
	can look up in the UI."""
	return v(rec, "CustomerID") or v(rec, "InventoryID") or v(rec, "ContactID") or "?"


def _log_issue(entity: str, remote_id: str, kind: str, detail: str) -> None:
	try:
		record_sync_issue(entity, remote_id, kind, detail)
	except Exception:
		# record_sync_issue does its own doc.save() and can fail in turn; losing the
		# ability to log one bad record must not abort the rest of the run.
		frappe.log_error(frappe.get_traceback(), "Acumatica sync issue recording failed")


def _retry_pending(client, pending: dict, counts: dict) -> None:
	"""Re-import the records earlier sweeps could not.

	A record usually fails on something outside itself -- a parent customer that had
	not arrived yet, a name an admin still has to free up -- and Acumatica will not
	send it again, because nothing about it was modified. The high-water-mark filter
	therefore skips it forever, so the failures are re-fetched by NoteID here instead."""
	# One request per queued NoteID, same as the paging loop's per-page requests --
	# the same licence rate cap applies, so it gets the same throttle.
	pause = float(client.settings.request_pause or 0)
	for entity, upsert, counter in _ENTITIES:
		queued = pending.get(entity) or {}
		for noteid, attempts in list(queued.items()):
			# Same one-savepoint-per-record reasoning as the main loop below.
			frappe.db.savepoint("acumatica_retry")
			rec = None
			try:
				page = client.get_page(entity, top=1, filter=f"NoteID eq guid'{noteid}'")
				if not page:
					# Deleted in Acumatica since it failed: there is nothing left to
					# import and nothing to warn anybody about.
					del queued[noteid]
					continue
				rec = page[0]
				if upsert(rec) is not None:
					counts[counter] += 1
				del queued[noteid]
			except Exception as e:
				frappe.db.rollback(save_point="acumatica_retry")
				attempts += 1
				if attempts < MAX_RETRY_ATTEMPTS:
					queued[noteid] = attempts
					continue
				del queued[noteid]
				counts["issues"] += 1
				# The first failure already wrote an "Import Failed" row; this is the
				# one that says nobody is coming back for it. If the fetch is what
				# failed there is no record to name it by, only the guid.
				_log_issue(entity, _remote_id(rec) if rec else noteid, "Gave Up", str(e))
			finally:
				if pause:
					time.sleep(pause)
		if not queued:
			# leave the field holding {} rather than a litter of empty entities
			pending.pop(entity, None)


def run_backfill(modified_since: str | None = None) -> dict:
	"""Import everything (or everything modified since the high-water mark).
	Records that fail land in the sync-issues table instead of aborting the run."""
	try:
		# The lock comes before everything, the settings read included: a second sync
		# has nothing useful to do, and two importers over the same pages write the
		# same documents from two transactions.
		with filelock(SYNC_JOB_ID, timeout=0):
			try:
				return _import_all(modified_since)
			except Exception as e:
				# The run died where the per-record savepoint could not catch it --
				# expired credentials, a dropped connection. Without this an admin sees
				# only a high-water mark that quietly stopped moving.
				frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", str(e)[:500])
				# the failing job's transaction is about to be rolled back around us
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
				raise
	except LockTimeoutError:
		# Not an error worth recording: the sweep runs nightly AND on every webhook, so
		# arriving while one is in flight is the ordinary busy case.
		frappe.logger("acumatica").info("a sync is already running; skipping this one")
		return {"skipped": "another sync is running"}


def _import_all(modified_since: str | None) -> dict:
	"""The body of a sync, with the lock already held."""
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

	pending = get_pending_retries()
	_retry_pending(client, pending, counts)

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
				_log_issue(entity, _remote_id(rec), "Import Failed", str(e))
				noteid = v(rec, "NoteID")
				if noteid:
					# Queue it for the next sweep. A record with no NoteID cannot be
					# fetched again, so there is nothing to retry with.
					#
					# setdefault, not assignment: a backfill passes no high-water mark,
					# so it re-scans the records the retry pass above has already tried
					# this run. Overwriting would hand the record a fresh attempt every
					# run and it would never reach the cap.
					pending.setdefault(entity, {}).setdefault(noteid, 1)
			done_in_entity += 1
			if done_in_entity % COMMIT_EVERY == 0:
				# A 50k-record backfill must not hold one transaction; committing per
				# page keeps locks short and preserves progress if the job dies.
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
		# Entity boundary: same reasoning as the per-page commit above.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	# Written last, and only here: everything above appends sync issues through
	# whole-document saves, which would carry a stale queue back over this one.
	set_pending_retries(pending)
	# High-water mark is when this run STARTED: anything modified mid-run is
	# picked up again next sweep rather than lost in the gap.
	frappe.db.set_single_value("CRM Acumatica Settings", "last_synced_at", started_at)
	# The run finished, so whatever killed the last one is history.
	frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", "")
	# The high-water mark must be durable the moment it is set -- the next sweep
	# reads it from a different worker process.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return counts


def schedule_sweep() -> None:
	"""Scheduler entry. It only enqueues: run inline it would hold a scheduler worker
	for the hours a first sync takes, and it would not be sharing the sync job id with
	the webhook and the manual backfill -- which is what keeps them to one at a time."""
	if not get_settings().enabled:
		return
	frappe.enqueue(
		"crm.integrations.acumatica.importer.nightly_sweep",
		queue="long",
		job_id=SYNC_JOB_ID,
		deduplicate=True,
		timeout=BACKFILL_TIMEOUT,
	)


def nightly_sweep() -> None:
	"""Scheduler entry. Webhooks are the latency mechanism; this is the
	correctness mechanism -- Acumatica keeps failed push notifications for
	only 2 days, so the sweep must always run."""
	settings = get_settings()
	if not settings.enabled:
		return
	since = settings.last_synced_at
	run_backfill(modified_since=str(since).replace(" ", "T") if since else None)
