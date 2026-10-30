# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Background worker + the single run-writer.

``run_enrichment`` is the enqueued job: it runs the pipeline (streaming progress
over realtime), writes a ``CRM Enrichment Run`` history record, applies the mapper
to the origin document, and publishes a terminal event. It NEVER raises to the
worker -- every failure is recorded on the Run, logged via ``frappe.log_error`` and
reported over realtime.

``write_run`` is the ONLY place that persists run history, so the storage choice
(standalone Run doctype today) stays swappable.
"""

from __future__ import annotations

import frappe
from frappe.utils.background_jobs import is_job_enqueued
from frappe.utils.telemetry import capture

from .config import (
	DEFAULT_SETTINGS,
	ENABLE_FLAG_BY_DOCTYPE,
	EnrichmentConfig,
	_setting,
	auto_enrich_enabled_for,
	enrichment_enabled_for,
	get_config,
	get_settings,
)
from .crawler import max_fetches
from .http import JobTimeout, _fetch_budget
from .mapper import apply_to_document, column_limit
from .pipeline import PROGRESS_STEPS
from .pipeline import run as run_pipeline

# Realtime event the frontend (Phase 6) subscribes to.
PROGRESS_EVENT = "domain_enrichment_progress"

# Total number of pipeline progress steps (mirrors pipeline.PROGRESS_STEPS).
TOTAL_STEPS = len(PROGRESS_STEPS)

# On top of the fetches and the model call: DNS lookups (outside the fetch budget),
# the Settings and document reads, the mapper, the save and the Run insert.
JOB_TIMEOUT_SLACK = 60


def _publish(reference_doctype, reference_name, status, message="", step=0, payload=None, user=None):
	"""Emit a single progress/terminal event. Mirrors crm/api/whatsapp.py shape:
	always carries the reference, plus step/total/message/status and an optional
	payload (terminal events put filled_fields/notes/result.flat() in the payload).
	Never raises -- realtime is best-effort."""
	try:
		frappe.publish_realtime(
			PROGRESS_EVENT,
			{
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"step": step,
				"total": TOTAL_STEPS,
				"message": message,
				"status": status,
				"payload": payload or {},
			},
			user=user,
		)
	except JobTimeout:
		raise
	except Exception:
		pass


def write_run(
	reference_doctype: str,
	reference_name: str,
	website: str,
	status: str,
	result=None,
	started_on=None,
	notes: str = "",
):
	"""Persist exactly one ``CRM Enrichment Run`` from an ``EnrichmentResult``.

	The single point of run-history writing -- storage stays swappable behind it.
	When ``result`` is given the summary fields + ``raw_json`` (full ``to_dict()``)
	are populated; otherwise a bare Run (status/website) is written.
	"""
	doc = frappe.new_doc("CRM Enrichment Run")
	doc.reference_doctype = reference_doctype
	doc.reference_name = reference_name
	doc.source_website = website
	doc.status = status
	doc.started_on = started_on or frappe.utils.now_datetime()
	if status in ("Completed", "Failed"):
		doc.finished_on = frappe.utils.now_datetime()
	if notes:
		doc.notes = notes

	if result is not None:
		# extract_social_profiles pre-seeds an empty entry per configured rule; only
		# summarise the networks that were actually found.
		social = ", ".join(sorted(k for k, v in result.social_profiles.items() if v.value))
		# Summary columns, cut to fit: an over-long scraped name must not fail the
		# insert, and the whole value is kept in raw_json.
		doc.company_name = (result.company_name.value or "")[: column_limit(doc.meta, "company_name")]
		doc.industry = (result.industry.value or "")[: column_limit(doc.meta, "industry")]
		doc.industry_confidence = result.industry_confidence or 0
		doc.emails_found = len(result.emails)
		doc.phones_found = len(result.phones)
		doc.social_profiles = social
		doc.raw_json = frappe.as_json(result.to_dict())
		if not notes and result.notes:
			doc.notes = "\n".join(result.notes)

	doc.insert(ignore_permissions=True)
	return doc.name


def job_timeout(s) -> int:
	"""Seconds the ``run_enrichment`` job may run: the run's own bounded worst case.

	Every fetch is held to the fetch budget and a run makes at most
	``crawler.max_fetches`` of them; with the model tier on, one completion adds up to
	the agent's ``timeout x MAX_ATTEMPTS``. The old ``request_timeout x max_pages + 60``
	(160 s by default) ignored the budget's multiple, the robots/sitemap/About fetches
	and the model, so rq's deadline landed mid-crawl on a site that was merely slow.
	"""
	cfg = EnrichmentConfig(settings={key: _setting(s, key) for key in DEFAULT_SETTINGS})
	per_fetch = _fetch_budget(cfg, int(cfg.setting("request_timeout")))
	seconds = max_fetches(int(cfg.setting("max_pages"))) * per_fetch + JOB_TIMEOUT_SLACK
	if int(cfg.setting("model_fallback") or 0):
		from crm.agent import client
		from crm.agent.config import DEFAULT_SETTINGS as AGENT_DEFAULTS
		from crm.agent.config import get_config as get_agent_config

		try:
			agent_timeout = get_agent_config().timeout
		except Exception:
			agent_timeout = AGENT_DEFAULTS["timeout"]
		seconds += agent_timeout * client.MAX_ATTEMPTS
	return int(seconds)


def enqueue_enrichment(
	reference_doctype: str, reference_name: str, website: str, user: str, trigger: str = "manual"
) -> dict:
	"""Enqueue one ``run_enrichment`` job (long queue, per-doc ``job_id`` +
	``deduplicate``, after commit). The single place the job is enqueued -- shared by
	the manual (``api.enrich``/``api.retry``) and auto (``after_insert``) paths so a
	manual click and an auto-fire never double-run, and the enqueue options stay in
	one spot. ``enqueue_after_commit`` matters for the ``after_insert`` caller, whose
	transaction has not committed yet; it is harmless for the already-saved paths.

	Reads only the Settings Single for the timeout bound (cheap, framework-cached) --
	it never assembles the full config.
	"""
	timeout = job_timeout(get_settings())
	job_id = f"domain-enrich-{reference_doctype}-{reference_name}"
	if is_job_enqueued(job_id):
		# frappe.enqueue would fold this into the job already queued or running, and
		# say nothing: that job reports to whoever enqueued it -- nobody, for the
		# nightly sweep -- so a caller told "queued" waited for an event that never
		# came. Say it is already running instead.
		return {"queued": False, "already_running": True, "job_id": job_id, "website": website}
	frappe.enqueue(
		"crm.domain_enrichment.tasks.run_enrichment",
		queue="long",
		timeout=timeout,
		job_id=job_id,
		deduplicate=True,
		enqueue_after_commit=True,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		website=website,
		user=user,
		trigger=trigger,
	)
	return {"queued": True, "job_id": job_id, "website": website, "timeout": timeout}


def auto_enrich_on_create(doc, method=None):
	"""Auto-enqueue enrichment for a new CRM record.

	Called from the ``after_insert`` of the CRM Lead / CRM Deal / CRM Organization
	controllers (the trigger stays visible where the record lives, rather than as a
	doc_events hook). Best-effort and never raises into the save. Fires only when the
	feature is enabled, ``auto_enrich`` is on, the doctype is enabled, and the record
	has a website. Reuses the same per-doc ``job_id``
	+ ``deduplicate`` as the manual ``api.enrich`` path, so a manual click and the
	auto-fire never double-run. A new Deal created with a website is therefore enriched
	alongside its Organization -- each crawls independently and writes its own fields.
	"""
	try:
		# Cheap Settings-only gate -- runs on every Lead/Deal/Org insert, so it must
		# not assemble the full config (Rules/Mappings). The worker builds that later.
		if not auto_enrich_enabled_for(doc.doctype):
			return

		website = (doc.get("website") or "").strip()
		if not website:
			return

		enqueue_enrichment(doc.doctype, doc.name, website, frappe.session.user, trigger="auto")
	except Exception:
		frappe.log_error(title="Domain Enrichment: auto_enrich_on_create failed")


def stale_records(doctype: str, cutoff, limit: int) -> list[tuple[str, str]]:
	"""``(name, website)`` of the records of ``doctype`` whose most recent run started
	before ``cutoff``.

	Oldest first, so a backlog is worked through in order instead of the sweep
	re-picking the same records every night.

	Deliberately joins against run history rather than scanning the doctype: a
	record that has *never* been enriched is not stale, it is untouched, and
	sweeping those in would mean ticking one checkbox crawls every website in the
	CRM that night. Never-enriched records are what the Enrich button and
	``auto_enrich`` are for.

	Only records that still exist and still have a website are returned. The sweep
	cannot enrich anything else, and skipping one writes no run that would age it
	out -- so, picked oldest first, a few deleted or website-less records took the
	whole batch every night and nothing behind them was ever reached.

	The latest run counts whatever its status -- a site that fails to crawl is
	retried on the same cadence as everything else, not every single night.
	"""
	from frappe.query_builder.functions import Max

	Run = frappe.qb.DocType("CRM Enrichment Run")
	Record = frappe.qb.DocType(doctype)
	last_started = Max(Run.started_on)
	rows = (
		frappe.qb.from_(Run)
		.join(Record)
		.on(Record.name == Run.reference_name)
		.select(Run.reference_name, Record.website)
		.where(Run.reference_doctype == doctype)
		.where(Record.website.isnotnull() & (Record.website != ""))
		.groupby(Run.reference_name, Record.website)
		.having(last_started < cutoff)
		.orderby(last_started)
		.limit(limit)
	).run()
	return [(name, website) for name, website in rows]


def reenrich_stale_records() -> int:
	"""Daily sweep: re-enqueue enrichment for records whose data has gone stale.

	Returns how many were enqueued. Off unless an admin turns
	``scheduled_reenrichment`` on -- crawling other people's websites on a timer is
	not something to start doing by default.

	Enqueues through the same ``enqueue_enrichment`` as the manual and auto paths,
	so the per-document ``job_id`` and ``deduplicate`` mean a record a rep is
	already enriching by hand is not run twice.
	"""
	s = get_settings()
	if not (_setting(s, "enabled") and _setting(s, "scheduled_reenrichment")):
		return 0

	days = max(1, int(_setting(s, "reenrich_after_days")))
	batch = max(1, int(_setting(s, "reenrich_batch_size")))
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -days)

	queued = 0
	for doctype in ENABLE_FLAG_BY_DOCTYPE:
		if queued >= batch or not enrichment_enabled_for(doctype):
			continue

		for name, website in stale_records(doctype, cutoff, batch - queued):
			try:
				enqueue_enrichment(doctype, name, website.strip(), user="Administrator", trigger="scheduled")
				queued += 1
			except Exception:
				# one unqueueable record must not cost the rest of the sweep
				frappe.log_error(title=f"Domain Enrichment: could not queue {doctype} {name}")

	if queued:
		frappe.logger("crm.enrichment").info(
			f"Scheduled re-enrichment queued {queued} record(s) stale for more than {days} days"
		)
	return queued


def run_enrichment(
	reference_doctype: str,
	reference_name: str,
	website: str,
	user: str | None = None,
	trigger: str = "manual",
):
	"""Enqueued worker: crawl, map onto the origin doc, write a Run, stream progress.

	Never raises to the worker. On success the mapped origin doc is saved (a normal
	permission-respecting save -- it is the doc the user triggered enrichment on; no
	related records are touched, that is Phase 5). On any exception the Run is marked
	Failed, logged, and an error event is published.
	"""
	user = user or frappe.session.user
	started_on = frappe.utils.now_datetime()

	# Nobody is waiting on a scheduled sweep. Publishing anyway would put a
	# progress stream for records they never asked about into whichever session
	# happens to be the job's user -- and publishing to no user at all is a
	# site-wide broadcast, which is worse. So the events are simply not sent.
	audience = None if trigger == "scheduled" else user

	def _notify(**kwargs):
		if audience:
			_publish(reference_doctype, reference_name, user=audience, **kwargs)

	def progress(step_index, message=""):
		_notify(status="running", message=message, step=step_index)

	try:
		cfg = get_config()
		_notify(status="running", message="Starting", step=0)

		result = run_pipeline(website, cfg=cfg, progress=progress)

		doc = frappe.get_doc(reference_doctype, reference_name)
		doc.check_permission("write")
		filled_fields = apply_to_document(doc, result, cfg)
		if filled_fields:
			doc.save()

		write_run(
			reference_doctype,
			reference_name,
			website,
			status="Completed",
			result=result,
			started_on=started_on,
		)

		_notify(
			status="completed",
			message="Completed",
			step=TOTAL_STEPS - 1,
			payload={
				"filled_fields": filled_fields,
				"notes": result.notes,
				**result.flat(),
			},
		)
		capture(
			"enrichment_run_completed",
			"crm",
			properties={
				"doctype": reference_doctype,
				"trigger": trigger,
				"status": "success",
			},
		)
	except Exception:
		# Discard any partial writes (e.g. a doc.save() that fired side effects before a
		# later step threw). execute_job commits when this function returns normally, so
		# without the rollback those partials would be committed alongside the Failed run.
		frappe.db.rollback()
		frappe.log_error(
			title="Domain Enrichment: run_enrichment failed",
			message=frappe.get_traceback(),
		)
		try:
			write_run(
				reference_doctype,
				reference_name,
				website,
				status="Failed",
				started_on=started_on,
				notes=frappe.utils.cstr(frappe.get_traceback())[:1000],
			)
		except Exception:
			frappe.log_error(title="Domain Enrichment: could not write Failed run")
		_notify(
			status="error",
			message=frappe._("Enrichment failed. Check the error log."),
			step=0,
		)
		capture(
			"enrichment_run_completed",
			"crm",
			properties={
				"doctype": reference_doctype,
				"trigger": trigger,
				"status": "failure",
			},
		)
