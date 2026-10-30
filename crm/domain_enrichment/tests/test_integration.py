# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""IntegrationTestCase tests for the Frappe layer (real test DB).

Covers: seeder idempotency, the mapper write-policies against real CRM
Lead/Deal/Organization docs, the single Run writer, API permission/allow-list
enforcement + preview rate-limit, and the link-time Organization -> Lead/Deal copy.

All tests are network-free: wherever a crawl would happen the pipeline / fetch is
monkeypatched to return a canned EnrichmentResult, so nothing leaves the box.
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from rq.timeouts import JobTimeoutException

from crm.domain_enrichment import config, install, tasks
from crm.domain_enrichment.config import get_config
from crm.domain_enrichment.cross_record import copy_enrichment_from_organization
from crm.domain_enrichment.mapper import apply_to_document
from crm.domain_enrichment.result import EnrichmentResult, Field, SocialProfile
from crm.domain_enrichment.tests import fixtures


def canned_result(website="https://acme.example") -> EnrichmentResult:
	"""A fully-populated EnrichmentResult — no network, deterministic."""
	r = EnrichmentResult(website=website)
	r.company_name = Field("Acme Analytics Inc.", website, "JSON-LD")
	r.description = Field("AI powered analytics SaaS for product teams.", website, "Meta Tag")
	r.logo = Field("https://acme.example/favicon.ico", website, "Favicon")
	r.industry = Field("SaaS", website, "Keyword Classifier")
	r.industry_confidence = 0.8
	r.social_profiles = {
		"linkedin": SocialProfile("https://www.linkedin.com/company/acme", website),
		"twitter": SocialProfile("https://twitter.com/acme", website),
	}
	return r


class SeederIdempotencyTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_seeder_is_a_no_op_on_second_run(self):
		# The seeder runs on install/migrate, so records already exist. Running it
		# again must not create duplicate Rule / Field Mapping rows.
		install.seed_default_rules_and_mappings()
		rules_before = frappe.db.count("CRM Enrichment Rule")
		mappings_before = frappe.db.count("CRM Enrichment Field Mapping")

		install.seed_default_rules_and_mappings()

		self.assertEqual(frappe.db.count("CRM Enrichment Rule"), rules_before)
		self.assertEqual(frappe.db.count("CRM Enrichment Field Mapping"), mappings_before)
		self.assertGreater(rules_before, 0)
		self.assertGreater(mappings_before, 0)


class SeedOnceTest(IntegrationTestCase):
	"""The seeder runs on every migrate. Keyed on names an admin can change, it put
	back every default they had deleted and duplicated every rule they had renamed."""

	def tearDown(self):
		frappe.db.rollback()

	def _marker(self):
		return frappe.db.get_singles_dict("CRM Enrichment Settings").get("seed_version")

	def test_a_deleted_default_stays_deleted(self):
		install.seed_default_rules_and_mappings()  # the site as an admin finds it
		mapping = {"source_key": "industry", "target_doctype": "CRM Deal", "target_fieldname": "industry"}
		frappe.db.delete("CRM Enrichment Field Mapping", mapping)
		frappe.db.delete("CRM Enrichment Rule", {"rule_name": "Industry: Ecommerce"})
		frappe.db.delete("CRM Industry", {"name": "Ecommerce"})

		install.seed_default_rules_and_mappings()  # the next migrate

		self.assertFalse(frappe.db.exists("CRM Enrichment Field Mapping", mapping))
		self.assertFalse(frappe.db.exists("CRM Enrichment Rule", {"rule_name": "Industry: Ecommerce"}))
		self.assertFalse(frappe.db.exists("CRM Industry", "Ecommerce"))

	def test_a_renamed_rule_is_not_seeded_again(self):
		install.seed_default_rules_and_mappings()
		frappe.db.set_value(
			"CRM Enrichment Rule",
			{"rule_name": "Industry: Manufacturing"},
			"rule_name",
			"Manufacturing (engineering)",
		)

		install.seed_default_rules_and_mappings()

		self.assertEqual(frappe.db.count("CRM Enrichment Rule", {"industry": "Manufacturing"}), 1)

	def test_a_site_seeded_before_the_marker_is_not_reseeded(self):
		"""Upgrading must not resurrect what was deleted under the old seeder either."""
		frappe.db.set_single_value("CRM Enrichment Settings", "seed_version", 0)
		frappe.db.delete("CRM Enrichment Rule", {"rule_name": "Industry: Ecommerce"})

		install.seed_default_rules_and_mappings()

		self.assertFalse(frappe.db.exists("CRM Enrichment Rule", {"rule_name": "Industry: Ecommerce"}))
		self.assertEqual(int(self._marker()), install.SEED_VERSION)

	def test_a_fresh_site_is_seeded_and_marked(self):
		frappe.db.set_single_value("CRM Enrichment Settings", "seed_version", 0)
		frappe.db.delete("CRM Enrichment Rule")
		frappe.db.delete("CRM Enrichment Field Mapping")

		install.seed_default_rules_and_mappings()

		self.assertTrue(frappe.db.exists("CRM Enrichment Rule", {"rule_name": "Industry: Ecommerce"}))
		self.assertTrue(frappe.db.count("CRM Enrichment Field Mapping"))
		self.assertEqual(int(self._marker()), install.SEED_VERSION)


class AnchorTwitterRulePatchTest(IntegrationTestCase):
	"""Sites seeded before the twitter pattern was anchored keep the old one until the
	patch replaces it -- but only where it is still the seeded text."""

	def tearDown(self):
		frappe.db.rollback()

	def _rule(self, pattern):
		return frappe.get_doc(
			{
				"doctype": "CRM Enrichment Rule",
				"rule_name": "QA twitter " + frappe.generate_hash(length=6),
				"rule_type": "Social",
				"target_value": "twitter",
				"match_scope": "HTML",
				"patterns": [{"pattern": pattern, "is_regex": 1}],
			}
		).insert(ignore_permissions=True)

	def test_the_seeded_pattern_is_anchored_and_an_admins_is_left_alone(self):
		from crm.patches.v1_0 import anchor_seeded_twitter_rule

		seeded = self._rule(install.TWITTER_PATTERN_V1)
		admins = self._rule(r"twitter\.com/acme_only")

		anchor_seeded_twitter_rule.execute()

		self.assertEqual(
			frappe.get_doc("CRM Enrichment Rule", seeded.name).patterns[0].pattern,
			install.SOCIAL_PATTERNS["twitter"][0],
		)
		self.assertEqual(
			frappe.get_doc("CRM Enrichment Rule", admins.name).patterns[0].pattern, r"twitter\.com/acme_only"
		)


class MapperWritePolicyTest(IntegrationTestCase):
	def setUp(self):
		self.cfg = get_config()
		self.result = canned_result()

	def tearDown(self):
		frappe.db.rollback()

	def _new_org(self, **kwargs):
		doc = frappe.new_doc("CRM Organization")
		doc.organization_name = kwargs.pop("organization_name", "Mapper Test Org")
		for k, v in kwargs.items():
			doc.set(k, v)
		return doc

	def test_fill_if_empty_fills_only_empty_fields(self):
		org = self._new_org(company_description="")
		apply_to_document(org, self.result, self.cfg)
		self.assertEqual(org.company_description, "AI powered analytics SaaS for product teams.")

	def test_fill_if_empty_never_clobbers_user_data(self):
		org = self._new_org(company_description="Hand-written by sales.")
		apply_to_document(org, self.result, self.cfg)
		self.assertEqual(org.company_description, "Hand-written by sales.")

	def test_a_value_too_long_for_its_column_is_skipped_not_fatal(self):
		"""Data fields are varchar(140), and frappe refuses the whole save over one value
		that does not fit -- so a LinkedIn URL with a tracking query string failed the
		run, rolled back every other field, and did the same on every retry."""
		long_linkedin = (
			"https://www.linkedin.com/company/mbp-engineering-pty-ltd/"
			"?viewAsMember=true&originalSubdomain=za&utm_source=website&utm_medium=footer&utm_campaign=social"
		)
		self.assertGreater(len(long_linkedin), 140)
		result = canned_result()
		result.social_profiles = {"linkedin": SocialProfile(long_linkedin, result.website)}
		cfg = fixtures.make_config(
			mappings_by_doctype={
				"CRM Organization": [
					fixtures.make_mapping("linkedin", "CRM Organization", "linkedin"),
					fixtures.make_mapping("description", "CRM Organization", "company_description"),
				]
			}
		)
		org = self._new_org(organization_name="Overlength Org " + frappe.generate_hash(length=4))

		apply_to_document(org, result, cfg)
		org.insert()

		self.assertFalse(org.linkedin)
		self.assertEqual(org.company_description, "AI powered analytics SaaS for product teams.")

	def test_create_missing_link_creates_industry(self):
		industry = "Quantum Widgets " + frappe.generate_hash(length=6)
		self.assertFalse(frappe.db.exists("CRM Industry", industry))
		result = canned_result()
		result.industry = Field(industry, "https://x.example", "Keyword Classifier")
		org = self._new_org(industry="")
		apply_to_document(org, result, self.cfg)
		self.assertTrue(frappe.db.exists("CRM Industry", industry))
		self.assertEqual(org.industry, industry)

	def test_create_missing_link_respects_user_create_permission(self):
		# A user without CRM Industry create rights must not be able to auto-create a
		# master from a scraped value: the master is not inserted and the field is
		# skipped (no dangling link), rather than an ignore_permissions escalation.
		industry = "Contraband Industry " + frappe.generate_hash(length=6)
		result = canned_result()
		result.industry = Field(industry, "https://x.example", "Keyword Classifier")
		org = self._new_org(industry="")

		user = _make_minimal_user()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(user)
		apply_to_document(org, result, self.cfg)

		self.assertFalse(frappe.db.exists("CRM Industry", industry))
		self.assertFalse(org.industry)


class RunWriterTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_writes_exactly_one_run_with_summary(self):
		org = frappe.new_doc("CRM Organization")
		org.organization_name = "Run Writer Org " + frappe.generate_hash(length=4)
		org.website = "https://acme.example"
		org.insert()

		before = frappe.db.count("CRM Enrichment Run", {"reference_name": org.name})
		run_name = tasks.write_run(
			"CRM Organization",
			org.name,
			"https://acme.example",
			status="Completed",
			result=canned_result(),
		)
		after = frappe.db.count("CRM Enrichment Run", {"reference_name": org.name})
		self.assertEqual(after - before, 1)

		run = frappe.get_doc("CRM Enrichment Run", run_name)
		self.assertEqual(run.status, "Completed")
		self.assertEqual(run.company_name, "Acme Analytics Inc.")
		self.assertEqual(run.industry, "SaaS")
		self.assertTrue(run.finished_on)
		self.assertIn("Acme Analytics", run.raw_json)

	def test_an_overlong_scraped_name_does_not_fail_the_run(self):
		"""The summary is history; cut to its column, the full value stays in raw_json."""
		org = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Long Name Org " + frappe.generate_hash(length=4),
			}
		).insert(ignore_permissions=True)
		result = canned_result()
		result.company_name = Field("M" * 150, result.website, "JSON-LD")

		run_name = tasks.write_run(
			"CRM Organization", org.name, "https://acme.example", "Completed", result=result
		)

		self.assertEqual(frappe.db.get_value("CRM Enrichment Run", run_name, "company_name"), "M" * 140)
		self.assertIn("M" * 150, frappe.db.get_value("CRM Enrichment Run", run_name, "raw_json"))


class JobTimeoutTest(IntegrationTestCase):
	"""rq's timeout must cover the run's own bounded worst case. At the old
	``request_timeout x max_pages + 60`` (160 s by default) it landed mid-crawl on a
	site that was merely slow, and the worker was killed with no Run written."""

	def tearDown(self):
		frappe.db.rollback()

	def _timeout(self, **settings):
		s = frappe._dict({"request_timeout": 10, "max_pages": 10, **settings})
		with (
			mock.patch.object(tasks, "get_settings", return_value=s),
			mock.patch.object(tasks.frappe, "enqueue") as enq,
		):
			tasks.enqueue_enrichment("CRM Organization", "O1", "https://acme.example", "Administrator")
		return enq.call_args.kwargs["timeout"]

	def test_it_covers_every_fetch_a_run_can_make(self):
		# robots.txt + 5 sitemaps + 10 pages + a second robots.txt + 4 About probes,
		# each allowed its whole fetch budget (3 x request_timeout, capped at 30 s)
		self.assertGreaterEqual(self._timeout(), 21 * 30)

	def test_it_grows_with_the_page_budget(self):
		self.assertGreaterEqual(self._timeout(max_pages=40) - self._timeout(), 30 * 30)

	def test_the_model_call_is_allowed_for_when_the_fallback_is_on(self):
		with mock.patch("crm.agent.config.get_config", return_value=frappe._dict(timeout=45)):
			self.assertGreaterEqual(self._timeout(model_fallback=1), 21 * 30 + 45 * 2)

	def test_the_job_deadline_while_publishing_stops_the_job(self):
		"""Realtime is best-effort; rq's deadline landing mid-publish is not a realtime
		failure, and swallowed there nothing else would ever stop the job."""
		with mock.patch.object(tasks.frappe, "publish_realtime", side_effect=JobTimeoutException("late")):
			with self.assertRaises(JobTimeoutException):
				tasks._publish("CRM Organization", "O1", "running", user="Administrator")

	def test_a_run_that_times_out_ends_failed_with_a_terminal_event(self):
		"""What letting the deadline through buys: run_enrichment's own handler records
		the Failed run and tells the button. (write_run is stubbed: the handler's
		rollback would also roll back a record inserted by this test.)"""
		published = []
		with (
			mock.patch.object(tasks, "run_pipeline", side_effect=JobTimeoutException("late")),
			mock.patch.object(tasks, "_publish", side_effect=lambda *a, **k: published.append(k)),
			mock.patch.object(tasks, "write_run") as write_run,
		):
			tasks.run_enrichment("CRM Organization", "O1", "https://slow.example", user="Administrator")

		self.assertEqual(write_run.call_args.kwargs["status"], "Failed")
		self.assertEqual(published[-1]["status"], "error")


class AlreadyRunningTest(IntegrationTestCase):
	"""A click while a run for the record is queued or running -- typically the
	nightly sweep's -- is folded into that run by frappe.enqueue, which reports to
	whoever enqueued it. Told "queued", the Enrich button waited for an event that
	never came."""

	def _enqueue(self, already_queued):
		with (
			mock.patch.object(tasks, "is_job_enqueued", return_value=already_queued) as probe,
			mock.patch.object(tasks.frappe, "enqueue") as enq,
		):
			answer = tasks.enqueue_enrichment("CRM Organization", "O1", "https://acme.example", "rep@x.test")
		probe.assert_called_once_with("domain-enrich-CRM Organization-O1")
		return answer, enq

	def test_a_deduplicated_click_is_not_told_it_was_queued(self):
		answer, enq = self._enqueue(already_queued=True)
		self.assertFalse(answer["queued"])
		self.assertTrue(answer["already_running"])
		enq.assert_not_called()

	def test_a_fresh_click_is_queued_with_its_deadline(self):
		answer, enq = self._enqueue(already_queued=False)
		self.assertTrue(answer["queued"])
		self.assertNotIn("already_running", answer)
		self.assertEqual(answer["timeout"], enq.call_args.kwargs["timeout"])


class EnrichedRecordDeleteTest(IntegrationTestCase):
	"""Every enriched record has CRM Enrichment Runs whose ``reference_name`` is a
	Dynamic Link to it. Nothing exempted or cleared them, so frappe refused to delete
	the record; the delete modal listed the runs, its Unlink did nothing to them and
	said it had, and its Delete needed write on a Run, which Sales roles lack."""

	def tearDown(self):
		frappe.db.rollback()

	def _enriched_org(self):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Enriched " + frappe.generate_hash(length=6)}
		).insert(ignore_permissions=True)
		run = tasks.write_run(
			"CRM Organization", org.name, "https://acme.example", "Completed", result=canned_result()
		)
		return org, run

	def test_an_enriched_record_can_be_deleted_and_takes_its_runs_with_it(self):
		for doctype, fields in (
			("CRM Organization", {"organization_name": "Enriched " + frappe.generate_hash(length=6)}),
			("CRM Lead", {"first_name": "Enriched", "lead_name": "Enriched Lead"}),
			("CRM Deal", {}),
		):
			with self.subTest(doctype=doctype):
				doc = frappe.get_doc({"doctype": doctype, **fields}).insert(ignore_permissions=True)
				run = tasks.write_run(doctype, doc.name, "https://acme.example", "Completed")

				frappe.delete_doc(doctype, doc.name)

				self.assertFalse(frappe.db.exists(doctype, doc.name))
				self.assertFalse(frappe.db.exists("CRM Enrichment Run", run))

	def test_runs_are_not_offered_by_the_delete_modal(self):
		from crm.api.doc import get_linked_docs_of_document

		org, _run = self._enriched_org()
		linked = get_linked_docs_of_document("CRM Organization", org.name)
		self.assertNotIn("CRM Enrichment Run", {row["reference_doctype"] for row in linked})

	def test_an_unlink_that_changed_nothing_is_reported_skipped(self):
		from crm.api.doc import remove_linked_doc_reference

		_org, run = self._enriched_org()
		answer = remove_linked_doc_reference([{"doctype": "CRM Enrichment Run", "docname": run}])
		self.assertEqual(answer["unlinked"], [])
		self.assertEqual(answer["skipped"], [{"docname": run, "reason": "not_unlinkable"}])

	def test_deleting_a_linked_document_takes_delete_permission_not_write(self):
		"""Sales Manager holds delete on a Run and not write."""
		from crm.api import doc as doc_api

		_org, run = self._enriched_org()

		def delete_only(doctype, ptype="read", doc=None, *args, **kwargs):
			return ptype == "delete"

		with mock.patch.object(doc_api.frappe, "has_permission", side_effect=delete_only):
			answer = doc_api.remove_linked_doc_reference(
				[{"doctype": "CRM Enrichment Run", "docname": run}], delete=True
			)
		self.assertEqual(answer, {"unlinked": [run], "skipped": []})
		self.assertFalse(frappe.db.exists("CRM Enrichment Run", run))


class ApiPermissionTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def test_enrich_throws_on_disallowed_doctype(self):
		from crm.domain_enrichment.api import enrich

		with self.assertRaises(frappe.ValidationError):
			enrich("ToDo", "anything")

	def test_a_disallowed_doctype_answers_the_same_whether_the_record_exists(self):
		"""``get_doc`` used to run before the allow-list, so "no such record" and
		"enrichment is not enabled for X" were two distinguishable answers for any
		doctype/name pair -- an existence oracle for records the caller cannot read.
		(``DoesNotExistError`` subclasses ``ValidationError``, which is why the
		test above passed either way.)"""
		from crm.domain_enrichment.api import enrich

		todo = frappe.get_doc({"doctype": "ToDo", "description": "enrich probe"}).insert(
			ignore_permissions=True
		)
		self.addCleanup(frappe.delete_doc, "ToDo", todo.name, force=True, ignore_permissions=True)

		answers = set()
		for name in (todo.name, "no-such-todo-at-all"):
			with self.assertRaises(frappe.ValidationError) as raised:
				enrich("ToDo", name)
			answers.add(str(raised.exception))
		self.assertEqual(len(answers), 1, answers)

	def test_enrich_requires_write_permission(self):
		from crm.domain_enrichment.api import enrich

		org = frappe.new_doc("CRM Organization")
		org.organization_name = "Perm Org " + frappe.generate_hash(length=4)
		org.website = "https://acme.example"
		org.insert()

		# A user with no role on CRM Organization must be blocked by check_permission.
		user = _make_minimal_user()
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			enrich("CRM Organization", org.name)

	def test_enrich_checks_the_allow_list_without_assembling_the_rules(self):
		from crm.domain_enrichment import api

		org = frappe.new_doc("CRM Organization")
		org.organization_name = "Allow-list Org " + frappe.generate_hash(length=4)
		org.website = "https://acme.example"
		org.insert()

		with (
			mock.patch.object(config, "_build_rules", side_effect=AssertionError("rules built")) as build,
			mock.patch.object(api, "enqueue_enrichment", return_value={"queued": True}) as enqueue,
		):
			api.enrich("CRM Organization", org.name)
		build.assert_not_called()
		enqueue.assert_called_once()

	def test_enrich_routes_are_rate_limited(self):
		# enrich / retry / enrich_preview each carry rate_limit(limit=ENRICH_RATE_LIMIT).
		from crm.domain_enrichment import api

		for fn in (api.enrich, api.retry, api.enrich_preview):
			self.assertTrue(hasattr(fn, "__wrapped__"), fn.__name__)

	def test_enrich_routes_are_rate_limited_per_user_too(self):
		"""``@rate_limit`` keys on the IP; the user-keyed layer refuses before any
		permission check or fetch, and covers all three entry points."""
		from unittest import mock

		from crm.domain_enrichment import api

		with mock.patch.object(api, "user_rate_limited", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				api.enrich("CRM Organization", "does-not-matter")
			with self.assertRaises(frappe.ValidationError):
				api.retry("does-not-matter")
			with self.assertRaises(frappe.ValidationError):
				api.enrich_preview("https://acme.example")


class CrossRecordCopyTest(IntegrationTestCase):
	def setUp(self):
		self.org = frappe.new_doc("CRM Organization")
		self.org.organization_name = "Enriched Org " + frappe.generate_hash(length=4)
		self.org.website = "https://acme.example"
		self.org.company_description = "AI powered analytics SaaS."
		self.org.linkedin = "https://www.linkedin.com/company/acme"
		self.org.insert()
		# Mark it enriched via a completed Run (the cleanest "is enriched" signal).
		tasks.write_run(
			"CRM Organization",
			self.org.name,
			self.org.website,
			status="Completed",
			result=canned_result(),
		)

	def tearDown(self):
		frappe.db.rollback()

	def test_copies_empty_fields_from_enriched_org(self):
		deal = frappe.new_doc("CRM Deal")
		deal.organization = self.org.name
		filled = copy_enrichment_from_organization(deal)
		self.assertTrue(filled)
		self.assertEqual(deal.company_description, "AI powered analytics SaaS.")
		self.assertEqual(deal.linkedin, "https://www.linkedin.com/company/acme")

	def test_the_copy_does_not_assemble_the_rules(self):
		"""It runs on every save of a Deal or Lead linked to an enriched org and uses
		only the field mappings; building the full config cost a get_doc per rule."""
		deal = frappe.new_doc("CRM Deal")
		deal.organization = self.org.name
		with mock.patch.object(config, "_build_rules", side_effect=AssertionError("rules built")) as build:
			filled = copy_enrichment_from_organization(deal)
		build.assert_not_called()
		self.assertTrue(filled)

	def test_does_not_clobber_user_set_fields(self):
		deal = frappe.new_doc("CRM Deal")
		deal.organization = self.org.name
		deal.company_description = "User wrote this."
		copy_enrichment_from_organization(deal)
		self.assertEqual(deal.company_description, "User wrote this.")

	def test_non_enriched_org_is_a_noop(self):
		plain = frappe.new_doc("CRM Organization")
		plain.organization_name = "Plain Org " + frappe.generate_hash(length=4)
		plain.website = "https://plain.example"
		plain.insert()

		deal = frappe.new_doc("CRM Deal")
		deal.organization = plain.name
		filled = copy_enrichment_from_organization(deal)
		self.assertEqual(filled, [])
		self.assertFalse(deal.company_description)


class AutoEnrichOnCreateTest(IntegrationTestCase):
	"""The after_insert auto-enrich hook (Organization + Deal), gated by Settings."""

	def _settings(self, **overrides):
		s = {
			"enabled": 1,
			"auto_enrich": 1,
			"enable_organization": 1,
			"enable_deal": 1,
			"request_timeout": 10,
			"max_pages": 10,
		}
		s.update(overrides)
		return frappe._dict(s)

	def _doc(self, doctype, website="https://acme.example", name="X1"):
		return frappe._dict(doctype=doctype, name=name, website=website)

	def _run(self, doc, settings):
		# auto_enrich_on_create now does a Settings-only gate (config.get_settings), and
		# enqueue_enrichment reads its timeout the same way -- patch both to the fake
		# Settings and assert on frappe.enqueue.
		with (
			mock.patch.object(config, "get_settings", return_value=settings),
			mock.patch.object(tasks, "get_settings", return_value=settings),
			mock.patch.object(tasks.frappe, "enqueue") as enq,
		):
			tasks.auto_enrich_on_create(doc)
		return enq

	def test_enqueues_for_new_deal(self):
		enq = self._run(self._doc("CRM Deal", name="D1"), self._settings())
		enq.assert_called_once()
		kwargs = enq.call_args.kwargs
		self.assertEqual(kwargs["reference_doctype"], "CRM Deal")
		self.assertEqual(kwargs["job_id"], "domain-enrich-CRM Deal-D1")
		self.assertTrue(kwargs["deduplicate"])

	def test_enqueues_for_new_organization(self):
		enq = self._run(self._doc("CRM Organization", name="O1"), self._settings())
		enq.assert_called_once()
		self.assertEqual(enq.call_args.kwargs["reference_doctype"], "CRM Organization")

	def test_skips_when_auto_enrich_off(self):
		enq = self._run(self._doc("CRM Deal"), self._settings(auto_enrich=0))
		enq.assert_not_called()

	def test_skips_when_doctype_disabled(self):
		enq = self._run(self._doc("CRM Deal"), self._settings(enable_deal=0))
		enq.assert_not_called()

	def test_skips_without_website(self):
		enq = self._run(self._doc("CRM Deal", website=""), self._settings())
		enq.assert_not_called()


def _make_minimal_user():
	"""Create (or reuse) a user with no CRM Organization role for permission tests."""
	email = "de-noperm@example.com"
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "No"
		user.last_name = "Perm"
		user.send_welcome_email = 0
		user.insert(ignore_permissions=True)
	return email
