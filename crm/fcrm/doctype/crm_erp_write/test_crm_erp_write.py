# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The ERP write ledger is the guard against a second keyless PUT into the client's
ERP. These pin what makes it one: the database, not the request, decides who holds a
target; it survives the request's rollback and a flush of the cache; and a closed row
is history, never a guard."""

import threading
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from crm.fcrm.doctype.crm_erp_write import crm_erp_write as ledger
from crm.utils.autonomous import autonomous_db

TARGET = "SalesOrder::LED-TEST-DEAL"


def _forget():
	"""Only this module's rows (every target it writes names an LED- record): the
	ledger is written on a committing connection, and a live guard on a site the
	suite is pointed at must never go with them."""
	with autonomous_db() as db:
		db.sql("delete from `tabCRM ERP Write` where target like %s", ("%::LED-%",))


def _rows(target=None):
	with autonomous_db() as db:
		return db.sql(
			"select name, target, open_key, state, attempts, remote_id, error, marker, triggered_by"
			" from `tabCRM ERP Write` where target = %s order by creation",
			(target or TARGET,),
			as_dict=True,
		)


def _in_workers(count, work):
	"""Run ``work()`` in ``count`` threads, each its own frappe site context and
	database connection, released together; their results and any errors."""
	site, sites_path = frappe.local.site, frappe.local.sites_path
	barrier = threading.Barrier(count)
	results, errors = [], []

	def run():
		frappe.init(site, sites_path=sites_path)
		frappe.connect()
		try:
			barrier.wait(timeout=30)
			results.append(work())
		except Exception as e:
			errors.append(e)
		finally:
			frappe.destroy()

	threads = [threading.Thread(target=run) for _ in range(count)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join(timeout=60)
	return results, errors


class TestERPWriteLedger(FrappeTestCase):
	def setUp(self):
		_forget()
		self.addCleanup(_forget)

	def test_two_workers_opening_the_same_write_one_wins(self):
		results, errors = _in_workers(4, lambda: ledger.acquire(TARGET, {"sent_at": 1.0}))
		self.assertEqual(errors, [])
		self.assertEqual(len([r for r in results if r]), 1, results)
		self.assertEqual(len(_rows()), 1)

	def test_two_retries_of_the_same_unanswered_write_one_takes_it_over(self):
		"""Both read the same open attempt and found nothing it made; only one may send."""
		ledger.acquire(TARGET, {"sent_at": 1.0})
		ledger.record_unknown(TARGET, "read timed out")
		seen = ledger.open_write(TARGET)

		results, errors = _in_workers(4, lambda: ledger.acquire(TARGET, {"sent_at": 2.0}, expected=seen))

		self.assertEqual(errors, [])
		self.assertEqual(len([r for r in results if r]), 1, results)
		row = ledger.open_write(TARGET)
		self.assertEqual((row.state, row.attempts, row.marker), (ledger.IN_FLIGHT, 2, {"sent_at": 2.0}))

	def test_an_unanswered_write_is_no_longer_the_attempt_a_stale_read_saw(self):
		"""A retry that read the row while its write was still in flight must not take
		it over once that write has come back unanswered: it never looked for what that
		write made."""
		ledger.acquire(TARGET, {"sent_at": 1.0})
		seen_in_flight = ledger.open_write(TARGET)
		ledger.record_unknown(TARGET, "504")
		self.assertIsNone(ledger.acquire(TARGET, {"sent_at": 2.0}, expected=seen_in_flight))
		self.assertTrue(ledger.acquire(TARGET, {"sent_at": 2.0}, expected=ledger.open_write(TARGET)))

	def _org(self, name):
		return frappe.get_doc({"doctype": "CRM Organization", "organization_name": name}).insert(
			ignore_permissions=True
		)

	def test_a_rename_moves_the_open_write_when_it_commits(self):
		from frappe.model.rename_doc import rename_doc

		self._org("LED-Rn Old")
		ledger.acquire("Customer::LED-Rn Old", {"sent_at": 1.0})
		ledger.acquire("CustomerContact::LED-Rn New", {"contact": "y"})
		ledger.acquire("CustomerContact::LED-Rn Old", {"contact": "x"})
		rename_doc("CRM Organization", "LED-Rn Old", "LED-Rn New", force=True, ignore_permissions=True)
		self.assertTrue(ledger.open_write("Customer::LED-Rn Old"), "moved only when the rename commits")
		frappe.db.before_commit.run()
		self.assertIsNone(ledger.open_write("Customer::LED-Rn Old"))
		self.assertTrue(ledger.open_write("Customer::LED-Rn New"))
		# the new name's own follow-up stands
		self.assertEqual(ledger.open_write("CustomerContact::LED-Rn New").marker, {"contact": "y"})

	def test_a_rename_that_rolls_back_leaves_the_open_write_where_it_was(self):
		from frappe.model.rename_doc import rename_doc

		self._org("LED-Rb Old")
		ledger.acquire("Customer::LED-Rb Old", {"sent_at": 1.0})
		rename_doc("CRM Organization", "LED-Rb Old", "LED-Rb New", force=True, ignore_permissions=True)
		frappe.db.rollback()
		frappe.db.before_commit.run()
		self.assertTrue(ledger.open_write("Customer::LED-Rb Old"))
		self.assertIsNone(ledger.open_write("Customer::LED-Rb New"))

	def test_a_rename_undone_by_the_importers_savepoint_leaves_the_open_write_where_it_was(self):
		"""The sync wraps each record in a savepoint; rolling one back runs no rollback
		hooks, and the sync's next commit must not move the row for a rename it undid."""
		from crm.integrations.acumatica.importer import _rename_organization

		self._org("LED-Sp Old")
		ledger.acquire("Customer::LED-Sp Old", {"sent_at": 1.0})
		frappe.db.savepoint("acumatica_rec")
		_rename_organization("LED-Sp Old", "LED-Sp New")
		frappe.db.rollback(save_point="acumatica_rec")
		frappe.db.before_commit.run()  # the sync's next commit
		self.assertTrue(ledger.open_write("Customer::LED-Sp Old"))
		self.assertIsNone(ledger.open_write("Customer::LED-Sp New"))

	def test_close_settles_only_the_row_and_version_it_names(self):
		ledger.acquire(TARGET, {"sent_at": 1.0})
		seen = ledger.open_write(TARGET)
		ledger.record_unknown(TARGET, "504")
		ledger.close(TARGET, ledger.ABANDONED, name=seen.name, version=seen.version)
		self.assertTrue(ledger.open_write(TARGET), "a row that changed since it was seen stays open")
		now = ledger.open_write(TARGET)
		ledger.close(TARGET, ledger.ABANDONED, name=now.name, version=now.version)
		self.assertIsNone(ledger.open_write(TARGET))

	def test_the_open_write_outlives_the_requests_rollback_and_the_cache(self):
		ledger.acquire(TARGET, {"sent_at": 1.0})
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.cache().delete_keys("")
		self.assertEqual(ledger.open_write(TARGET).marker, {"sent_at": 1.0})
		self.assertIsNone(ledger.acquire(TARGET, {"sent_at": 2.0}))

	def test_settled_only_when_the_request_commits(self):
		ledger.acquire(TARGET, {"sent_at": 1.0})
		ledger.close_after_commit(TARGET, remote_id="QT000900")
		frappe.db.rollback()
		self.assertTrue(ledger.open_write(TARGET), "a rolled-back request must leave the write open")

		ledger.close_after_commit(TARGET, remote_id="QT000900")
		frappe.db.after_commit.run()
		self.assertIsNone(ledger.open_write(TARGET))
		(row,) = _rows()
		self.assertEqual((row.state, row.remote_id, row.open_key), (ledger.APPLIED, "QT000900", None))

	def test_a_closed_write_is_history_and_the_next_one_opens_a_new_row(self):
		ledger.acquire(TARGET, {"sent_at": 1.0})
		ledger.close(TARGET, ledger.REFUSED, error="422 credit hold")
		self.assertTrue(ledger.acquire(TARGET, {"sent_at": 2.0}))
		rows = _rows()
		self.assertEqual([r.state for r in rows], [ledger.REFUSED, ledger.IN_FLIGHT])
		self.assertEqual(rows[0].error, "422 credit hold")
		self.assertEqual(rows[0].triggered_by, "Administrator")

	def test_a_rename_moves_the_open_write(self):
		old, new = "Customer::LED-Old", "Customer::LED-New"
		ledger.acquire(old, {"sent_at": 1.0, "name": "LED Old"})
		ledger.move(old, new)
		self.assertIsNone(ledger.open_write(old))
		self.assertEqual(ledger.open_write(new).marker["name"], "LED Old")
		self.assertEqual(_rows(new)[0].open_key, new)

	def test_a_rename_onto_a_name_with_its_own_open_write_keeps_that_one(self):
		old, new = "Customer::LED-Old", "Customer::LED-New"
		ledger.acquire(old, {"sent_at": 1.0})
		ledger.acquire(new, {"sent_at": 2.0})
		ledger.move(old, new)
		self.assertEqual(ledger.open_write(new).marker, {"sent_at": 2.0})
		self.assertEqual(_rows(old)[0].state, ledger.ABANDONED)

	def test_the_purge_drops_old_closed_rows_and_never_an_open_one(self):
		closed, kept_open = "SalesOrder::LED-Closed", "SalesOrder::LED-Open"
		ledger.acquire(closed, {"sent_at": 1.0})
		ledger.close(closed, ledger.APPLIED)
		ledger.acquire(kept_open, {"sent_at": 1.0})
		ledger.record_unknown(kept_open, "read timed out")
		long_ago = add_days(now_datetime(), -ledger.KEEP_CLOSED_DAYS - 1)
		with autonomous_db() as db:
			db.sql(
				"update `tabCRM ERP Write` set finished_at = %s, modified = %s, started_at = %s",
				(long_ago, long_ago, long_ago),
			)

		ledger.purge_settled()

		self.assertEqual(_rows(closed), [])
		self.assertEqual(ledger.open_write(kept_open).state, ledger.UNKNOWN)

	def test_no_role_may_write_it_by_hand(self):
		perms = frappe.get_meta("CRM ERP Write").permissions
		self.assertEqual([p.role for p in perms], ["System Manager"])
		self.assertFalse(any(p.write or p.create or p.delete for p in perms))


class TestCarryOverPatch(FrappeTestCase):
	"""An upgrade during an unanswered push must not open a duplicate window."""

	KEYS = (
		"acumatica_inflight::SalesOrder::LED-PATCH-DEAL",
		"acumatica_inflight::Customer::LED-PATCH-ORG",
		"acumatica_inflight::CustomerContact::LED-PATCH-ORG",
		"acumatica_inflight::CustomerPushSweep::ran",
	)

	def setUp(self):
		_forget()
		self.addCleanup(_forget)
		self.addCleanup(lambda: frappe.cache().delete_value(list(self.KEYS)))

	def test_live_markers_become_open_rows_once(self):
		from crm.patches.v1_0 import carry_acumatica_inflight_markers_to_ledger as patch

		cache = frappe.cache()
		cache.set_value(self.KEYS[0], 1763290000.5)
		cache.set_value(self.KEYS[1], {"sent_at": 1.0, "preexisting": ["C-OLD"], "name": "LED Patch"})
		cache.set_value(self.KEYS[2], "LED-CONTACT")
		cache.set_value(self.KEYS[3], 1.0)

		patch.execute()
		patch.execute()  # idempotent

		order = ledger.open_write("SalesOrder::LED-PATCH-DEAL")
		self.assertEqual((order.state, order.marker), (ledger.UNKNOWN, {"sent_at": 1763290000.5}))
		customer = ledger.open_write("Customer::LED-PATCH-ORG")
		self.assertEqual(customer.marker["preexisting"], ["C-OLD"])
		self.assertEqual(
			ledger.open_write("CustomerContact::LED-PATCH-ORG").marker, {"contact": "LED-CONTACT"}
		)
		with autonomous_db() as db:
			self.assertEqual(
				db.sql("select count(*) from `tabCRM ERP Write` where target like %s", ("%::LED-%",))[0][0], 3
			)

	def test_a_bare_timestamp_customer_marker_keeps_its_ambiguity(self):
		from crm.patches.v1_0 import carry_acumatica_inflight_markers_to_ledger as patch

		frappe.cache().set_value(self.KEYS[1], 1700000000.0)
		patch.execute()
		self.assertEqual(
			ledger.open_write("Customer::LED-PATCH-ORG").marker,
			{"sent_at": 1700000000.0, "preexisting": None},
		)

	def test_markers_survive_the_clear_cache_migrate_runs_before_its_patches(self):
		"""SiteMigration.setUp calls frappe.clear_cache() before either patch pass: a
		marker not in persistent_cache_keys is gone before the patch can read it."""
		from crm.patches.v1_0 import carry_acumatica_inflight_markers_to_ledger as patch

		frappe.cache().set_value(self.KEYS[0], 1763290000.5)
		frappe.clear_cache()
		patch.execute()
		self.assertEqual(ledger.open_write("SalesOrder::LED-PATCH-DEAL").marker, {"sent_at": 1763290000.5})

	def test_an_unreachable_redis_fails_the_patch_so_migrate_runs_it_again(self):
		import redis

		from crm.patches.v1_0 import carry_acumatica_inflight_markers_to_ledger as patch

		with mock_patch.object(frappe.cache, "ping", side_effect=redis.exceptions.ConnectionError("down")):
			with self.assertRaises(redis.exceptions.ConnectionError):
				patch.execute()

	def test_nothing_in_redis_does_nothing(self):
		from crm.patches.v1_0 import carry_acumatica_inflight_markers_to_ledger as patch

		frappe.cache().delete_value(list(self.KEYS))
		patch.execute()
		with autonomous_db() as db:
			self.assertEqual(
				db.sql("select count(*) from `tabCRM ERP Write` where target like %s", ("%::LED-%",))[0][0], 0
			)
