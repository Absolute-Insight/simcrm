# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests import IntegrationTestCase


def _a_zone_far_from_the_os_clock() -> str:
	"""A site time zone at least ten hours away from the container's own clock, so
	a stamp read off the OS clock cannot agree with the site clock by luck. CI and
	test_site both run UTC, which is why the bug never showed there; production
	runs +02:00."""
	os_offset = datetime.now().astimezone().utcoffset()
	for zone in ("Pacific/Kiritimati", "Etc/GMT+12"):
		if abs(datetime.now(ZoneInfo(zone)).utcoffset() - os_offset) >= timedelta(hours=10):
			return zone
	raise AssertionError("no candidate time zone is far enough from the OS clock")


class TestCRMStatusChangeLog(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		stages = frappe.get_all(
			"CRM Deal Status",
			filters={"type": ("in", ("Open", "Ongoing"))},
			order_by="position asc",
			pluck="name",
		)
		if len(stages) < 2:
			self.skipTest("site needs two open deal statuses")
		self.first, self.second = stages[:2]
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Status Log Clock Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)

	def test_stage_change_stamps_are_on_the_site_clock(self):
		"""days_in_stage subtracts a stamp from now_datetime(), so the stamp has
		to be on that clock too or the count ticks over hours early."""
		with patch("frappe.utils.data.get_system_timezone", return_value=_a_zone_far_from_the_os_clock()):
			site_now = frappe.utils.now_datetime()
			deal = frappe.get_doc(
				{"doctype": "CRM Deal", "organization": self.org, "status": self.first}
			).insert(ignore_permissions=True)
			self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)
			deal.status = self.second
			deal.save(ignore_permissions=True)

		log = frappe.get_doc("CRM Deal", deal.name).status_change_log
		stamps = {
			"entered first stage": log[0].from_date,
			"left first stage": log[0].to_date,
			"entered second stage": log[1].from_date,
		}
		for what, stamp in stamps.items():
			drift = abs(frappe.utils.get_datetime(stamp) - site_now)
			self.assertLess(drift, timedelta(minutes=5), f"{what} stamped {stamp}, site clock {site_now}")
