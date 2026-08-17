# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Label existing forecast snapshots with the scope they were always written at.

Before CRM Forecast Snapshot carried a ``scope``, the user field alone said what
a row meant: blank was the site-wide aggregate, anything else was one rep. Both
readings survive exactly, so this is a relabelling and not a recomputation --
which matters, because a stored forecast records what was believed on a past
date and cannot be recovered if it is thrown away.

Team rows are not backfilled. They never existed, and there is no honest way to
invent one: summing the rep rows double-counts a deal owned by one member and
assigned to another, and reflects today's ownership rather than the ownership on
the snapshot date. Team accuracy therefore accumulates from the next weekly run
forward, and the chart says so instead of showing a number nobody measured.
"""

import frappe


def execute():
	if not frappe.db.has_column("CRM Forecast Snapshot", "scope"):
		return

	Snapshot = frappe.qb.DocType("CRM Forecast Snapshot")
	frappe.qb.update(Snapshot).set(Snapshot.scope, "Site").where(
		(Snapshot.user == "") | Snapshot.user.isnull()
	).run()
	frappe.qb.update(Snapshot).set(Snapshot.scope, "Rep").where(
		Snapshot.user.notnull() & (Snapshot.user != "")
	).run()
