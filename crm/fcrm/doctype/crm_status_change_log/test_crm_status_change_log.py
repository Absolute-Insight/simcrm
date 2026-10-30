# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime, now_datetime


def _a_zone_far_from_the_os_clock() -> str:
	"""A site time zone at least ten hours away from the container's own clock."""
	os_offset = datetime.now().astimezone().utcoffset()
	for zone in ("Pacific/Kiritimati", "Etc/GMT+12"):
		if abs(datetime.now(ZoneInfo(zone)).utcoffset() - os_offset) >= timedelta(hours=10):
			return zone
	raise AssertionError("no candidate time zone is far enough from the OS clock")


class TestCRMStatusChangeLog(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_log_times_are_read_off_the_site_clock(self):
		"""datetime.now() is the container's clock, not the site's. Prod runs UTC
		containers for a +02:00 site, so every stage was stamped two hours early
		and days_in_stage, which compares them with now_datetime(), read a day
		short across midnight."""
		with patch("frappe.utils.data.get_system_timezone", return_value=_a_zone_far_from_the_os_clock()):
			deal = frappe.get_doc({"doctype": "CRM Deal", "status": "Qualification"}).insert(
				ignore_permissions=True
			)
			deal.status = "Demo/Making"
			deal.save(ignore_permissions=True)

			site_now = now_datetime()
			first, second = deal.status_change_log[-2:]
			for label, value in (
				("closed stage's to_date", first.to_date),
				("open stage's from_date", second.from_date),
			):
				with self.subTest(label):
					self.assertLess(abs(get_datetime(value) - site_now), timedelta(minutes=5))
