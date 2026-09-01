import json

import frappe
from frappe import _
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.desk.form.assign_to import set_status
from frappe.model import no_value_fields
from frappe.model.delete_doc import get_dynamic_linked_docs, get_linked_docs
from frappe.model.document import get_controller
from frappe.utils import cint, make_filter_tuple
from pypika import Criterion

from crm.api.views import get_views
from crm.fcrm.doctype.crm_form_script.crm_form_script import get_form_script
from crm.utils import is_frappe_version

# Hard ceilings on what one list or kanban request may pull; the client's
# "load more" steps below these, and a crafted page_length no longer does.
MAX_PAGE_LENGTH = 1000
MAX_KANBAN_COLUMN_PAGE_LENGTH = 500

COUNT_NAME = (
	{"COUNT": "name", "as": "total_count"}
	if is_frappe_version("16", above=True)
	else "count(name) as total_count"
)


@frappe.whitelist()
def sort_options(doctype: str):
	frappe.has_permission(doctype, "read", throw=True)
	fields = frappe.get_meta(doctype).fields
	fields = [field for field in fields if field.fieldtype not in no_value_fields]
	fields = [
		{
			"label": _(field.label),
			"value": field.fieldname,
			"fieldname": field.fieldname,
		}
		for field in fields
		if field.label and field.fieldname
	]

	standard_fields = [
		{"label": "Name", "fieldname": "name"},
		{"label": "Created On", "fieldname": "creation"},
		{"label": "Last Modified", "fieldname": "modified"},
		{"label": "Modified By", "fieldname": "modified_by"},
		{"label": "Owner", "fieldname": "owner"},
	]

	for field in standard_fields:
		field["label"] = _(field["label"])
		field["value"] = field["fieldname"]
		fields.append(field)

	return fields


@frappe.whitelist()
def get_filterable_fields(doctype: str):
	allowed_fieldtypes = [
		"Check",
		"Data",
		"Float",
		"Int",
		"Currency",
		"Dynamic Link",
		"Link",
		"Long Text",
		"Select",
		"Small Text",
		"Text Editor",
		"Text",
		"Duration",
		"Rating",
		"Date",
		"Datetime",
	]

	frappe.has_permission(doctype, "read", throw=True)
	c = get_controller(doctype)
	restricted_fields = []
	if hasattr(c, "get_non_filterable_fields"):
		restricted_fields = c.get_non_filterable_fields()

	fields = []

	meta = frappe.get_meta(doctype).as_dict()

	# append standard fields (getting error when using frappe.model.std_fields)
	standard_fields = [
		{"fieldname": "name", "fieldtype": "Link", "label": "Name", "options": doctype},
		{"fieldname": "owner", "fieldtype": "Link", "label": "Created By", "options": "User"},
		{
			"fieldname": "modified_by",
			"fieldtype": "Link",
			"label": "Last Updated By",
			"options": "User",
		},
		{"fieldname": "_user_tags", "fieldtype": "Data", "label": "Tags"},
		{"fieldname": "_liked_by", "fieldtype": "Data", "label": "Like"},
		{"fieldname": "_comments", "fieldtype": "Text", "label": "Comments"},
		{"fieldname": "_assign", "fieldtype": "Text", "label": "Assigned To"},
		{"fieldname": "creation", "fieldtype": "Datetime", "label": "Created On"},
		{"fieldname": "modified", "fieldtype": "Datetime", "label": "Last Updated On"},
	]

	for field in standard_fields + meta.get("fields", []):
		if field.get("fieldname") not in restricted_fields and field.get("fieldtype") in allowed_fieldtypes:
			field["name"] = field.get("fieldname")
			field["label"] = _(field.get("label"))
			field["value"] = field.get("fieldname")
			fields.append(field)

	return fields


@frappe.whitelist()
def get_group_by_fields(doctype: str):
	allowed_fieldtypes = [
		"Check",
		"Data",
		"Float",
		"Int",
		"Currency",
		"Dynamic Link",
		"Link",
		"Select",
		"Duration",
		"Date",
		"Datetime",
	]

	frappe.has_permission(doctype, "read", throw=True)
	fields = frappe.get_meta(doctype).fields
	fields = [
		field
		for field in fields
		if field.fieldtype not in no_value_fields and field.fieldtype in allowed_fieldtypes
	]
	fields = [
		{
			"label": _(field.label),
			"fieldname": field.fieldname,
		}
		for field in fields
		if field.label and field.fieldname
	]

	standard_fields = [
		{"label": "Name", "fieldname": "name"},
		{"label": "Created On", "fieldname": "creation"},
		{"label": "Last Modified", "fieldname": "modified"},
		{"label": "Modified By", "fieldname": "modified_by"},
		{"label": "Owner", "fieldname": "owner"},
		{"label": "Like", "fieldname": "_liked_by"},
		{"label": "Assigned To", "fieldname": "_assign"},
		{"label": "Comments", "fieldname": "_comments"},
		{"label": "Created On", "fieldname": "creation"},
		{"label": "Modified On", "fieldname": "modified"},
	]

	for field in standard_fields:
		field["label"] = _(field["label"])
		fields.append(field)

	return fields


@frappe.whitelist()
def get_quick_filters(doctype: str, cached: bool = True):
	frappe.has_permission(doctype, "read", throw=True)
	meta = frappe.get_meta(doctype, cached)
	quick_filters = []

	if global_settings := frappe.db.exists("CRM Global Settings", {"dt": doctype, "type": "Quick Filters"}):
		_quick_filters = frappe.db.get_value("CRM Global Settings", global_settings, "json")
		_quick_filters = json.loads(_quick_filters) or []

		fields = []

		for filter in _quick_filters:
			if filter == "name":
				fields.append({"label": "Name", "fieldname": "name", "fieldtype": "Data"})
			else:
				field = next((f for f in meta.fields if f.fieldname == filter), None)
				if field:
					fields.append(field)

	else:
		fields = [field for field in meta.fields if field.in_standard_filter]

	for field in fields:
		options = field.get("options")
		if field.get("fieldtype") == "Select" and options and isinstance(options, str):
			options = options.split("\n")
			options = [{"label": option, "value": option} for option in options]
			if not any([not option.get("value") for option in options]):
				options.insert(0, {"label": "", "value": ""})
		quick_filters.append(
			{
				"label": _(field.get("label")),
				"fieldname": field.get("fieldname"),
				"fieldtype": field.get("fieldtype"),
				"options": options,
			}
		)

	if doctype == "CRM Lead":
		quick_filters = [filter for filter in quick_filters if filter.get("fieldname") != "converted"]

	return quick_filters


@frappe.whitelist()
def update_quick_filters(quick_filters: str, old_filters: str, doctype: str):
	frappe.only_for(["Sales Manager", "System Manager"], True)
	quick_filters = json.loads(quick_filters)
	old_filters = json.loads(old_filters)

	new_filters = [filter for filter in quick_filters if filter not in old_filters]
	removed_filters = [filter for filter in old_filters if filter not in quick_filters]

	# update or create global quick filter settings
	create_update_global_settings(doctype, quick_filters)

	# remove old filters
	for filter in removed_filters:
		update_in_standard_filter(filter, doctype, 0)

	# add new filters
	for filter in new_filters:
		update_in_standard_filter(filter, doctype, 1)


def create_update_global_settings(doctype, quick_filters):
	if global_settings := frappe.db.exists("CRM Global Settings", {"dt": doctype, "type": "Quick Filters"}):
		frappe.db.set_value("CRM Global Settings", global_settings, "json", json.dumps(quick_filters))
	else:
		# create CRM Global Settings doc
		doc = frappe.new_doc("CRM Global Settings")
		doc.dt = doctype
		doc.type = "Quick Filters"
		doc.json = json.dumps(quick_filters)
		doc.insert()


def update_in_standard_filter(fieldname, doctype, value):
	if property_name := frappe.db.exists(
		"Property Setter",
		{"doc_type": doctype, "field_name": fieldname, "property": "in_standard_filter"},
	):
		frappe.db.set_value("Property Setter", property_name, "value", value)
	else:
		make_property_setter(
			doctype,
			fieldname,
			"in_standard_filter",
			value,
			"Check",
			validate_fields_for_doctype=False,
		)


@frappe.whitelist()
def get_data(
	doctype: str,
	filters: dict,
	order_by: str,
	page_length: int = 20,
	page_length_count: int = 20,
	column_field: str | None = None,
	title_field: str | None = None,
	columns: str | list | None = None,
	rows: str | list | None = None,
	kanban_columns: str | list | None = None,
	kanban_fields: str | list | None = None,
	view: str | dict | None = None,
	default_filters: dict | None = None,
):
	custom_view = False
	page_length = min(cint(page_length) or 20, MAX_PAGE_LENGTH)
	page_length_count = min(cint(page_length_count) or 20, MAX_PAGE_LENGTH)
	filters = frappe._dict(filters)
	rows = frappe.parse_json(rows or "[]")
	columns = frappe.parse_json(columns or "[]")
	kanban_fields = frappe.parse_json(kanban_fields or "[]")
	kanban_columns = frappe.parse_json(kanban_columns or "[]")

	custom_view_name = view.get("custom_view_name") if view else None
	view_type = view.get("view_type") if view else None
	group_by_field = view.get("group_by_field") if view else None

	for key in filters:
		value = filters[key]
		if isinstance(value, list):
			if "@me" in value:
				value[value.index("@me")] = frappe.session.user
			elif "%@me%" in value:
				index = [i for i, v in enumerate(value) if v == "%@me%"]
				for i in index:
					value[i] = "%" + frappe.session.user + "%"
		elif value == "@me":
			filters[key] = frappe.session.user

	if default_filters:
		default_filters = frappe.parse_json(default_filters)
		filters.update(default_filters)

	is_default = True
	data = []
	_list = get_controller(doctype)
	default_rows = []
	if hasattr(_list, "default_list_data"):
		default_rows = _list.default_list_data().get("rows")

	meta = frappe.get_meta(doctype)

	if view_type != "kanban":
		if columns or rows:
			custom_view = True
			is_default = False
			columns = frappe.parse_json(columns)
			rows = frappe.parse_json(rows)

		if not columns:
			columns = [
				{"label": "Name", "type": "Data", "key": "name", "width": "16rem"},
				{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
			]

		if not rows:
			rows = ["name"]

		default_view_filters = {
			"dt": doctype,
			"type": view_type or "list",
			"is_standard": 1,
			"user": frappe.session.user,
		}

		if not custom_view and frappe.db.exists("CRM View Settings", default_view_filters):
			list_view_settings = frappe.get_doc("CRM View Settings", default_view_filters)
			columns = frappe.parse_json(list_view_settings.columns)
			rows = frappe.parse_json(list_view_settings.rows)
			is_default = False
		elif not custom_view or (is_default and hasattr(_list, "default_list_data")):
			rows = default_rows
			columns = _list.default_list_data().get("columns")

		# check if rows has all keys from columns if not add them
		visible_columns = []
		for column in columns:
			if column.get("key") not in rows:
				rows.append(column.get("key"))
			column["label"] = _(column.get("label"))

			if column.get("key") == "_liked_by" and column.get("width") == "10rem":
				column["width"] = "50px"

			# Drop the column if the field is hidden. Built as a new list rather
			# than removed in place: removing from the list being iterated moves
			# every later element down one and the loop skips the next, so a
			# hidden column that happened to follow another hidden one was never
			# examined and stayed in the view.
			column_meta = meta.get_field(column.get("key"))
			if column_meta and column_meta.get("hidden"):
				continue

			visible_columns.append(column)

		columns = visible_columns

		# check if rows has group_by_field if not add it
		if group_by_field and group_by_field not in rows:
			rows.append(group_by_field)

		data = (
			frappe.get_list(
				doctype,
				fields=rows,
				filters=filters,
				order_by=order_by,
				page_length=page_length,
			)
			or []
		)
		data = parse_list_data(data, doctype)

	if view_type == "kanban":
		if not rows:
			rows = default_rows

		if not kanban_columns and column_field:
			field_meta = frappe.get_meta(doctype).get_field(column_field)
			if field_meta.fieldtype == "Link":
				kanban_columns = frappe.get_all(
					field_meta.options,
					fields=["name"],
					order_by="modified asc",
				)
			elif field_meta.fieldtype == "Select":
				kanban_columns = [{"name": option} for option in field_meta.options.split("\n")]

		if not title_field:
			title_field = "name"
			if hasattr(_list, "default_kanban_settings"):
				title_field = _list.default_kanban_settings().get("title_field")

		if title_field not in rows:
			rows.append(title_field)

		if not kanban_fields:
			kanban_fields = ["name"]
			if hasattr(_list, "default_kanban_settings"):
				kanban_fields = json.loads(_list.default_kanban_settings().get("kanban_fields"))

		for field in kanban_fields:
			if field not in rows:
				rows.append(field)

		for kc in kanban_columns:
			# Start with base filters
			column_filters = []

			# Convert and add the main filters first
			if filters:
				base_filters = convert_filter_to_tuple(doctype, filters)
				column_filters.extend(base_filters)

			# Add the column-specific filter
			if column_field and kc.get("name"):
				column_filters.append([doctype, column_field, "=", kc.get("name")])

			order = kc.get("order")
			if kc.get("delete"):
				column_data = []
			else:
				page_length = min(cint(kc.get("page_length")) or 20, MAX_KANBAN_COLUMN_PAGE_LENGTH)
				if "page_length" in kc:
					kc["page_length"] = page_length

				if order:
					column_data = get_records_based_on_order(
						doctype, rows, column_filters, page_length, order
					)
				else:
					column_data = frappe.get_list(
						doctype,
						fields=rows,
						filters=column_filters,
						order_by=order_by,
						page_length=page_length,
					)

				all_count = frappe.get_list(
					doctype,
					filters=column_filters,
					fields=[COUNT_NAME],
				)[0].total_count

				kc["all_count"] = all_count
				kc["count"] = len(column_data)

			if order:
				column_data = sorted(
					column_data,
					key=lambda x: order.index(x.get("name")) if x.get("name") in order else len(order),
				)

			data.append({"column": kc, "fields": kanban_fields, "data": column_data})

	fields = frappe.get_meta(doctype).fields
	fields = [field for field in fields if field.fieldtype not in no_value_fields]
	fields = [
		{
			"label": _(field.label),
			"fieldtype": field.fieldtype,
			"fieldname": field.fieldname,
			"options": field.options,
		}
		for field in fields
		if field.label and field.fieldname
	]

	std_fields = [
		{"label": "Name", "fieldtype": "Data", "fieldname": "name"},
		{"label": "Created On", "fieldtype": "Datetime", "fieldname": "creation"},
		{"label": "Last Modified", "fieldtype": "Datetime", "fieldname": "modified"},
		{
			"label": "Modified By",
			"fieldtype": "Link",
			"fieldname": "modified_by",
			"options": "User",
		},
		{"label": "Assigned To", "fieldtype": "Text", "fieldname": "_assign"},
		{"label": "Owner", "fieldtype": "Link", "fieldname": "owner", "options": "User"},
		{"label": "Like", "fieldtype": "Data", "fieldname": "_liked_by"},
	]

	for field in std_fields:
		if field.get("fieldname") not in rows:
			rows.append(field.get("fieldname"))
		if field not in fields:
			field["label"] = _(field["label"])
			fields.append(field)

	if not is_default and custom_view_name:
		is_default = frappe.db.get_value("CRM View Settings", custom_view_name, "load_default_columns")

	if group_by_field and view_type == "group_by":

		def get_options(type, options):
			if type == "Select":
				return [option for option in options.split("\n")]
			else:
				has_empty_values = any([not d.get(group_by_field) for d in data])
				options = list(set([d.get(group_by_field) for d in data]))
				options = [u for u in options if u]
				if has_empty_values:
					options.append("")

				if order_by and group_by_field in order_by:
					order_by_fields = order_by.split(",")
					order_by_fields = [
						(field.split(" ")[0], field.split(" ")[1]) for field in order_by_fields
					]
					if (group_by_field, "asc") in order_by_fields:
						options.sort()
					elif (group_by_field, "desc") in order_by_fields:
						options.sort(reverse=True)
				else:
					options.sort()
				return options

		for field in fields:
			if field.get("fieldname") == group_by_field:
				group_by_field = {
					"label": field.get("label"),
					"fieldname": field.get("fieldname"),
					"fieldtype": field.get("fieldtype"),
					"options": get_options(field.get("fieldtype"), field.get("options")),
				}

	return {
		"data": data,
		"columns": columns,
		"rows": rows,
		"fields": fields,
		"column_field": column_field,
		"title_field": title_field,
		"kanban_columns": kanban_columns,
		"kanban_fields": kanban_fields,
		"group_by_field": group_by_field,
		"page_length": page_length,
		"page_length_count": page_length_count,
		"is_default": is_default,
		"views": get_views(doctype),
		"total_count": frappe.get_list(doctype, filters=filters, fields=[COUNT_NAME])[0].total_count,
		"row_count": len(data),
		"form_script": get_form_script(doctype),
		"list_script": get_form_script(doctype, "List"),
		"view_type": view_type,
	}


def parse_list_data(data, doctype):
	_list = get_controller(doctype)
	if hasattr(_list, "parse_list_data"):
		data = _list.parse_list_data(data)
	return data


def convert_filter_to_tuple(doctype, filters):
	if isinstance(filters, dict):
		filters_items = filters.items()
		filters = []
		for key, value in filters_items:
			filters.append(make_filter_tuple(doctype, key, value))
	return filters


def get_records_based_on_order(doctype, rows, filters, page_length, order):
	records = []
	filters = convert_filter_to_tuple(doctype, filters)
	in_filters = filters.copy()
	in_filters.append([doctype, "name", "in", order[:page_length]])
	records = frappe.get_list(
		doctype,
		fields=rows,
		filters=in_filters,
		order_by="creation desc",
		page_length=page_length,
	)

	if len(records) < page_length:
		not_in_filters = filters.copy()
		not_in_filters.append([doctype, "name", "not in", order])
		remaining_records = frappe.get_list(
			doctype,
			fields=rows,
			filters=not_in_filters,
			order_by="creation desc",
			page_length=page_length - len(records),
		)
		for record in remaining_records:
			records.append(record)

	return records


@frappe.whitelist()
def remove_assignments(doctype: str, name: str, assignees: str | list):
	"""Cancel the ToDo assignments named in ``assignees``.

	``ignore_permissions`` used to be a parameter here, which made it a *client*
	parameter: whitelisted arguments arrive from the request, and
	``set_status`` skips its permission check entirely when the flag is set. Any
	authenticated user could unassign anyone from any record, including records
	they cannot read -- and since a ToDo assignment is one of the clauses that
	grants a rep visibility of a deal, that is a way to take a record away from
	the rep who owns it. Neither caller ever passed it.
	"""
	assignees = frappe.parse_json(assignees)

	if not assignees:
		return

	for assign_to in assignees:
		set_status(doctype, name, todo=None, assign_to=assign_to, status="Cancelled")


@frappe.whitelist()
def get_assigned_users(doctype: str, name: str | int, default_assigned_to: str | None = None):
	"""Who is assigned to a record — for a caller who may read that record.

	``assigned_users`` reads ToDo through ``frappe.get_all``, which does not
	check permissions, and ToDo carries no CRM permission condition of its own.
	Whitelisted, that let any authenticated user name any record and learn who
	works it, walking the org chart one document at a time. Authority for the
	assignee list comes from the record: if you may read it, you may see who is
	on it.

	The unguarded :func:`assigned_users` stays available to server-side callers
	that legitimately need the list outside a session — notifying assignees of
	an inbound WhatsApp message is not the requester's read.
	"""
	if not frappe.has_permission(doctype, "read", doc=name):
		frappe.throw(_("Not permitted to read {0} {1}").format(doctype, name), frappe.PermissionError)

	return assigned_users(doctype, name, default_assigned_to)


def assigned_users(doctype: str, name: str | int, default_assigned_to: str | None = None):
	"""The raw assignee list, with no permission check. Server-side callers only."""
	allocated = frappe.get_all(
		"ToDo",
		fields=["allocated_to"],
		filters={
			"reference_type": doctype,
			"reference_name": name,
			"status": ("not in", ("Closed", "Cancelled")),
		},
		pluck="allocated_to",
	)

	users = list(set(allocated))

	# if users is empty, add default_assigned_to
	if not users and default_assigned_to:
		users = [default_assigned_to]
	return users


@frappe.whitelist()
def get_fields(doctype: str, allow_all_fieldtypes: bool = False):
	not_allowed_fieldtypes = [*list(frappe.model.no_value_fields), "Read Only"]
	if allow_all_fieldtypes:
		not_allowed_fieldtypes = []
	frappe.has_permission(doctype, "read", throw=True)
	fields = frappe.get_meta(doctype).fields

	_fields = []

	for field in fields:
		if field.fieldtype not in not_allowed_fieldtypes and field.fieldname:
			_fields.append(field)

	return _fields


def getCounts(d, doctype):
	d["_email_count"] = (
		frappe.db.count(
			"Communication",
			filters={
				"reference_doctype": doctype,
				"reference_name": d.get("name"),
				"communication_type": "Communication",
			},
		)
		or 0
	)
	d["_email_count"] = d["_email_count"] + frappe.db.count(
		"Communication",
		filters={
			"reference_doctype": doctype,
			"reference_name": d.get("name"),
			"communication_type": "Automated Message",
		},
	)
	d["_comment_count"] = frappe.db.count(
		"Comment",
		filters={"reference_doctype": doctype, "reference_name": d.get("name"), "comment_type": "Comment"},
	)
	d["_task_count"] = frappe.db.count(
		"CRM Task", filters={"reference_doctype": doctype, "reference_docname": d.get("name")}
	)
	d["_note_count"] = frappe.db.count(
		"FCRM Note", filters={"reference_doctype": doctype, "reference_docname": d.get("name")}
	)
	return d


# Linked-doc titles are read per reference doctype in one permission-aware
# list query, not one get_doc + has_permission per row. Special cases keep the
# titles the modal has always shown.
_LINKED_DOC_TITLE_FIELDS = {
	"CRM Call Log": ["from", "to"],
	"CRM Deal": ["organization"],
	"CRM Notification": ["message"],
}


def _linked_doc_title_fields(doctype: str) -> list[str]:
	if doctype in _LINKED_DOC_TITLE_FIELDS:
		return _LINKED_DOC_TITLE_FIELDS[doctype]
	meta = frappe.get_meta(doctype)
	for fieldname in ("title", meta.title_field):
		if fieldname and fieldname != "name" and meta.has_field(fieldname):
			return [fieldname]
	return []


def _linked_doc_title(doctype: str, row: dict) -> str:
	if doctype == "CRM Call Log":
		return f"Call from {row.get('from')} to {row.get('to')}"
	for fieldname in _linked_doc_title_fields(doctype):
		if row.get(fieldname):
			return row[fieldname]
	return row["name"]


@frappe.whitelist()
def get_linked_docs_of_document(doctype: str, docname: str):
	try:
		doc = frappe.get_doc(doctype, docname)
	except frappe.DoesNotExistError:
		return []
	doc.check_permission("read")

	linked_docs = get_linked_docs(doc)
	dynamic_linked_docs = get_dynamic_linked_docs(doc)

	linked_docs.extend(dynamic_linked_docs)
	linked_docs = list({doc["reference_docname"]: doc for doc in linked_docs}.values())

	names_by_doctype: dict[str, list[str]] = {}
	for doc in linked_docs:
		if not doc.get("reference_doctype") or not doc.get("reference_docname"):
			continue
		names_by_doctype.setdefault(doc["reference_doctype"], []).append(doc["reference_docname"])

	# One permission-aware list per reference doctype: rows the user cannot
	# read, and rows that no longer exist, simply do not come back.
	rows_by_key: dict[tuple[str, str], dict] = {}
	for reference_doctype, names in names_by_doctype.items():
		if not frappe.db.exists("DocType", reference_doctype):
			continue
		fields = ["name", *_linked_doc_title_fields(reference_doctype)]
		for row in frappe.get_list(reference_doctype, filters={"name": ("in", names)}, fields=fields):
			rows_by_key[(reference_doctype, row["name"])] = row

	docs_data = []
	for doc in linked_docs:
		row = rows_by_key.get((doc.get("reference_doctype"), doc.get("reference_docname")))
		if row is None:
			continue

		docs_data.append(
			{
				"doc": doc["reference_doctype"],
				"title": _linked_doc_title(doc["reference_doctype"], row),
				"reference_docname": doc["reference_docname"],
				"reference_doctype": doc["reference_doctype"],
			}
		)
	return docs_data


def remove_doc_link(doctype, docname):
	if not doctype or not docname:
		return

	try:
		linked_doc_data = frappe.get_doc(doctype, docname)
		if doctype == "CRM Notification":
			delete_notification_type = {
				"notification_type_doctype": "",
				"notification_type_doc": "",
			}
			delete_references = {
				"reference_doctype": "",
				"reference_name": "",
			}

			if linked_doc_data.get("notification_type_doctype") == linked_doc_data.get("reference_doctype"):
				delete_references.update(delete_notification_type)

			linked_doc_data.update(delete_references)
		else:
			linked_doc_data.update(
				{
					"reference_doctype": "",
					"reference_docname": "",
				}
			)
		linked_doc_data.save(ignore_permissions=True)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		pass


def remove_contact_link(doctype, docname):
	if not doctype or not docname:
		return

	try:
		linked_doc_data = frappe.get_doc(doctype, docname)
		linked_doc_data.update(
			{
				"contact": None,
				"contacts": [],
			}
		)
		linked_doc_data.save(ignore_permissions=True)
	except (frappe.DoesNotExistError, frappe.ValidationError):
		pass


@frappe.whitelist()
def remove_linked_doc_reference(items: str | list, remove_contact: bool = False, delete: bool = False):
	if isinstance(items, str):
		items = frappe.parse_json(items)

	# Report what happened rather than "success". Items are skipped for three
	# ordinary reasons -- malformed entry, no write permission, gone or invalid --
	# and the caller used to be told the same thing either way, so a modal closed
	# and a list reloaded over records that are all still there.
	unlinked: list[str] = []
	skipped: list[dict] = []

	for item in items:
		if not item.get("doctype") or not item.get("docname"):
			skipped.append({"docname": item.get("docname"), "reason": "invalid"})
			continue

		if not frappe.has_permission(item["doctype"], "write", item["docname"]):
			skipped.append({"docname": item["docname"], "reason": "no_permission"})
			continue

		try:
			if remove_contact:
				remove_contact_link(item["doctype"], item["docname"])
			else:
				remove_doc_link(item["doctype"], item["docname"])

			if delete:
				frappe.delete_doc(item["doctype"], item["docname"])
		except (frappe.DoesNotExistError, frappe.ValidationError) as exc:
			skipped.append({"docname": item["docname"], "reason": str(exc)[:200]})
			continue

		unlinked.append(item["docname"])

	return {"unlinked": unlinked, "skipped": skipped}


BULK_DELETE_LIMIT = 500


def _unlink_linked_docs(doctype: str, items: list, delete_linked: bool = False):
	for doc in items:
		try:
			if not frappe.db.exists(doctype, doc):
				frappe.log_error(f"Document {doctype} {doc} does not exist", "Bulk Delete Error")
				continue

			linked_docs = get_linked_docs_of_document(doctype, doc)
			for linked_doc in linked_docs:
				if not linked_doc.get("reference_doctype") or not linked_doc.get("reference_docname"):
					continue

				remove_linked_doc_reference(
					[
						{
							"doctype": linked_doc["reference_doctype"],
							"docname": linked_doc["reference_docname"],
						}
					],
					remove_contact=doctype == "Contact",
					delete=delete_linked,
				)
		except Exception as e:
			frappe.log_error(f"Error processing linked docs for {doctype} {doc}: {e!s}", "Bulk Delete Error")


def delete_bulk_docs_job(doctype: str, items: list, delete_linked: bool = False):
	"""The background half of delete_bulk_docs: unlink, then delete, as the enqueuing user."""
	from frappe.desk.reportview import delete_bulk

	_unlink_linked_docs(doctype, items, delete_linked)
	delete_bulk(doctype, items)


@frappe.whitelist()
def delete_bulk_docs(doctype: str, items: str | list, delete_linked: bool = False):
	from frappe.desk.reportview import delete_bulk

	if not doctype:
		frappe.throw(_("Doctype is required"))

	if not items:
		frappe.throw(_("Items are required"))

	items = frappe.parse_json(items)
	if not isinstance(items, list):
		frappe.throw(_("Items must be a list"))

	if len(items) > BULK_DELETE_LIMIT:
		frappe.throw(
			_("You can delete at most {0} records at once; {1} were selected.").format(
				BULK_DELETE_LIMIT, len(items)
			)
		)

	# Over ten, the unlinking and the delete both happen in a worker, so the
	# request path only enqueues. Saying "success" for that was the same word
	# used for "these are gone", so a rep watched a list reload with every
	# record still on it and no reason given. `queued` lets the caller say
	# "deleting in the background" instead of implying it is already done.
	if len(items) > 10:
		frappe.enqueue(
			"crm.api.doc.delete_bulk_docs_job",
			doctype=doctype,
			items=items,
			delete_linked=delete_linked,
		)
		return {"queued": True, "count": len(items)}

	_unlink_linked_docs(doctype, items, delete_linked)
	delete_bulk(doctype, items)
	return {"queued": False, "count": len(items)}
