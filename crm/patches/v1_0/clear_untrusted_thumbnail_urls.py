"""Clear every File.thumbnail_url this app did not set.

Before crm.utils.thumbnails guarded it, anyone who could write a File could set
``thumbnail_url`` through the REST API -- and frappe deletes whatever it names
from disk when that File is deleted. So a value already there may point at
someone else's file. Only one kind is kept: the URL of a thumbnail row this
module made *for that File* (``crm_thumbnail_of`` names it).

Nothing is deleted from disk. A value frappe's own ``make_thumbnail`` once
wrote names a real file under public/files that only that row used; the row
merely stops referring to it (the hourly backfill makes a private-safe
thumbnail in its place). Batched and idempotent: a second run finds nothing.
"""

import click
import frappe
from pypika.terms import ExistsCriterion

from crm.utils.thumbnails import FIELD, ensure_thumbnail_field

BATCH = 1000


def execute():
	ensure_thumbnail_field()
	File = frappe.qb.DocType("File")
	Thumb = frappe.qb.DocType("File").as_("thumb")
	own = (
		frappe.qb.from_(Thumb)
		.select(Thumb.name)
		.where(Thumb[FIELD] == File.name)
		.where(Thumb.file_url == File.thumbnail_url)
	)
	cleared = 0
	while True:
		names = (
			frappe.qb.from_(File)
			.select(File.name)
			.where(File.thumbnail_url.isnotnull() & (File.thumbnail_url != ""))
			.where(ExistsCriterion(own).negate())
			.limit(BATCH)
			.run(pluck=True)
		)
		if not names:
			break
		frappe.qb.update(File).set(File.thumbnail_url, None).where(File.name.isin(names)).run()
		cleared += len(names)
	if cleared:
		click.secho(f"* Cleared thumbnail_url on {cleared} File rows this app did not set")
