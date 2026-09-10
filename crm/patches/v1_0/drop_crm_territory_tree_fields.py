"""CRM Territory stops claiming to be a tree it never was.

The doctype shipped with ``is_tree``, ``nsm_parent_field`` and the whole nested-set
field set (``lft``, ``rgt``, ``is_group``, ``parent_crm_territory``, ``old_parent``)
next to a ``territory_manager`` link -- but the controller is a plain ``Document``,
not ``NestedSet``, so nothing ever maintained the tree, no code reads any of those
fields, and every territory filter in the app is an equality match. The desk offered
an admin a tree view in which provinces could be nested into regions, and then nothing
rolled up.

The fields are gone from the JSON. Frappe never drops a column on its own, so this
removes the leftovers -- but only where they hold nothing, which is every site that
took the model at its word and left the tree alone. Where someone did build a
hierarchy the columns stay and the data with them: silently destroying it would be
far worse than six unused columns, and the warning names them so it can be exported.
"""

import click
import frappe

DEAD_COLUMNS = (
	"parent_crm_territory",
	"old_parent",
	"territory_manager",
	"lft",
	"rgt",
	"is_group",
)


def execute():
	if not frappe.db.table_exists("CRM Territory"):
		return

	columns = set(frappe.db.get_table_columns("CRM Territory"))
	present = [column for column in DEAD_COLUMNS if column in columns]
	if not present:
		return

	used = [column for column in present if _holds_data(column)]
	if used:
		click.secho(
			"CRM Territory is no longer a tree. These columns still hold data and have been "
			f"left in place so nothing is lost: {', '.join(used)}.",
			fg="yellow",
		)
		return

	for column in present:
		frappe.db.sql_ddl(f"alter table `tabCRM Territory` drop column `{column}`")
	frappe.clear_cache(doctype="CRM Territory")


def _holds_data(column: str) -> bool:
	"""Raw SQL on purpose: the column is no longer in the meta, so the query
	builder will not accept it. '' and 0 both read as empty -- the int columns
	default to 0."""
	# A column name cannot be a bound parameter, so it has to be interpolated.
	# Refusing anything outside DEAD_COLUMNS makes that safe by construction
	# instead of by the caller's good behaviour, which is what lets the
	# interpolation below stand.
	if column not in DEAD_COLUMNS:
		raise ValueError(f"refusing to query an unknown column: {column!r}")

	return bool(
		frappe.db.sql(  # nosemgrep: frappe-sql-format-injection
			f"select 1 from `tabCRM Territory` where ifnull(`{column}`, '') not in ('', '0') limit 1"
		)
	)
