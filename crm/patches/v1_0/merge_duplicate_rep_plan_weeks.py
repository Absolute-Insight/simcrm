# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Merge duplicate rep-weeks so the unique index can be added without losing plans.

``CRM Rep Plan`` used to enforce one plan per (user, week) with a read-then-throw
in ``validate``, which two concurrent saves could both pass. Sites that ran that
code can hold two plans for the same rep-week, and the unique index added in
``on_doctype_update`` cannot be created while they do.

This runs **pre_model_sync**, before the doctype sync that adds the index, and it
*merges*: every item on the losing plans is moved onto the survivor, so no
planned activity and no fulfilment the matcher recorded is lost. Only a plan
that has been emptied by that move is deleted.

The survivor is the oldest plan for the week — it is the one anything else is
most likely to have been looking at — and every decision is printed, because a
migration that silently rewrites someone's week is worse than one that fails.
"""

import frappe

# Two items are the same planned activity if they say the same thing about the
# same record on the same day. Anything else is a genuinely separate item, even
# if it looks similar.
IDENTITY_FIELDS = ("activity_type", "planned_date", "reference_doctype", "reference_docname", "note")


def execute():
	if not frappe.db.table_exists("CRM Rep Plan"):
		return

	duplicates = frappe.db.sql(
		"""select `user`, week_start, count(*) as copies
		from `tabCRM Rep Plan`
		group by `user`, week_start having count(*) > 1""",
		as_dict=True,
	)
	if duplicates:
		print(f"CRM Rep Plan: merging {len(duplicates)} duplicated rep-week(s)")
		for row in duplicates:
			_merge_week(row.user, str(row.week_start))

	# The index lives in on_doctype_update, which frappe only calls when the
	# doctype's schema actually changes — so an upgrade that happens not to touch
	# CRM Rep Plan's JSON would merge the duplicates and still leave the site
	# without the constraint that stops them coming back. Ensure it here, where
	# we have just guaranteed the table can accept it.
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import on_doctype_update

	on_doctype_update()


def _merge_week(user: str, week_start: str) -> None:
	plans = frappe.get_all(
		"CRM Rep Plan",
		filters={"user": user, "week_start": week_start},
		fields=["name", "creation"],
		order_by="creation asc, name asc",
	)
	if len(plans) < 2:
		return

	keep = frappe.get_doc("CRM Rep Plan", plans[0].name)
	losers = [p.name for p in plans[1:]]

	# Read every losing item into memory *before* anything is deleted, so the move
	# is a copy-then-drop rather than a drop-then-hope. The patch runs inside the
	# migrate transaction, so a failure below rolls the deletes back too.
	incoming = [_copy(item) for name in losers for item in frappe.get_doc("CRM Rep Plan", name).items]

	# The losers have to go before the survivor is saved: `validate` refuses a plan
	# whose (user, week) already belongs to another, and until they are gone that
	# is exactly what the survivor looks like.
	for loser_name in losers:
		frappe.delete_doc("CRM Rep Plan", loser_name, force=True, ignore_permissions=True)

	seen = {_identity(item): item for item in keep.items}
	moved = 0
	for item in incoming:
		key = _identity(item)
		existing = seen.get(key)
		if existing is None:
			keep.append("items", item)
			seen[key] = keep.items[-1]
			moved += 1
		elif _is_fulfilled(item) and not _is_fulfilled(existing):
			# the same activity recorded twice, once with the matcher's verdict on
			# it — keep the verdict rather than the blank
			for field in ("status", "fulfilled_by_doctype", "fulfilled_by", "manual_override"):
				existing.set(field, item.get(field))

	keep.save(ignore_permissions=True)

	# names are autoincrement ints, so stringify before joining
	removed = ", ".join(str(name) for name in losers)
	print(
		f"  {user} week of {week_start}: kept {keep.name}, "
		f"moved {moved} item(s) from {len(losers)} duplicate(s), removed {removed}"
	)


def _identity(item) -> tuple:
	"""Works for both a child Document and the plain dict `_copy` produces."""
	get = item.get if hasattr(item, "get") else item.__getitem__
	return tuple(str(get(field) or "") for field in IDENTITY_FIELDS)


def _is_fulfilled(item) -> bool:
	return bool(item.get("fulfilled_by")) or item.get("status") in ("Done", "Missed")


def _copy(item) -> dict:
	fields = (
		*IDENTITY_FIELDS,
		"status",
		"fulfilled_by_doctype",
		"fulfilled_by",
		"manual_override",
		"suggestion",
	)
	return {field: item.get(field) for field in fields}
