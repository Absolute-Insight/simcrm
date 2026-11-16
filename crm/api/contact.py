import frappe
from frappe import _


def validate(doc, method):
	refuse_unreadable_address(doc)
	update_deals_email_mobile_no(doc)


def refuse_unreadable_address(doc):
	"""A contact is given an address its editor can read.

	An address goes with the contact that names it, so pointing one's own
	contact at an address at a colleague's customer hid that address from the
	colleague: link validation only asks whether it exists. Only an address that
	is new on the contact is checked -- one a manager put there stays -- and
	server code that saves on a rep's behalf is trusted.
	"""
	if doc.flags.ignore_permissions or not doc.address:
		return
	if not doc.is_new() and not doc.has_value_changed("address"):
		return
	from crm.permissions.customers import assert_address_allowed

	assert_address_allowed(doc.address)


def update_deals_email_mobile_no(doc):
	deal_names = frappe.get_all(
		"CRM Contacts",
		filters={"contact": doc.name, "is_primary": 1, "parenttype": "CRM Deal"},
		pluck="parent",
		distinct=True,
	)
	if not deal_names:
		return

	# one read and one write for every linked deal rather than a pair per deal
	deals = frappe.get_all(
		"CRM Deal",
		filters={"name": ("in", deal_names)},
		fields=["name", "email", "mobile_no"],
	)
	to_update = [d.name for d in deals if d.email != doc.email_id or d.mobile_no != doc.mobile_no]
	if to_update:
		frappe.db.set_value(
			"CRM Deal",
			{"name": ("in", to_update)},
			{"email": doc.email_id, "mobile_no": doc.mobile_no},
		)


@frappe.whitelist()
def get_linked_deals(contact: str):
	"""Get linked deals for a contact"""

	if not frappe.has_permission("Contact", "read", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	deal_names = frappe.get_all(
		"CRM Contacts",
		filters={"contact": contact, "parenttype": "CRM Deal"},
		pluck="parent",
		distinct=True,
	)
	if not deal_names:
		return []

	# get_list, not get_cached_doc: the rows come back through the deal's own
	# permission query, so a contact shared across teams shows only the deals
	# the caller may read
	return frappe.get_list(
		"CRM Deal",
		filters={"name": ("in", deal_names)},
		fields=[
			"name",
			"organization",
			"currency",
			"deal_value",
			"status",
			"email",
			"mobile_no",
			"deal_owner",
			"modified",
		],
		order_by="modified desc",
	)


@frappe.whitelist()
def create_new(contact: str, field: str, value: str):
	"""Create new email or phone for a contact"""
	if not frappe.has_permission("Contact", "write", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	contact = frappe.get_cached_doc("Contact", contact)

	if field == "email":
		email = {"email_id": value, "is_primary": 1 if len(contact.email_ids) == 0 else 0}
		contact.append("email_ids", email)
	elif field in ("mobile_no", "phone"):
		mobile_no = {"phone": value, "is_primary_mobile_no": 1 if len(contact.phone_nos) == 0 else 0}
		contact.append("phone_nos", mobile_no)
	else:
		frappe.throw(_("Invalid field"))

	contact.save()
	return True


@frappe.whitelist()
def set_as_primary(contact: str, field: str, value: str):
	"""Set email or phone as primary for a contact"""
	if not frappe.has_permission("Contact", "write", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	contact = frappe.get_doc("Contact", contact)

	if field == "email":
		for email in contact.email_ids:
			if email.email_id == value:
				email.is_primary = 1
			else:
				email.is_primary = 0
	elif field in ("mobile_no", "phone"):
		name = "is_primary_mobile_no" if field == "mobile_no" else "is_primary_phone"
		for phone in contact.phone_nos:
			if phone.phone == value:
				phone.set(name, 1)
			else:
				phone.set(name, 0)
	else:
		frappe.throw(_("Invalid field"))

	contact.save()
	return True


@frappe.whitelist()
def find_by_email(email: str) -> str | None:
	"""The Contact the caller can read that carries ``email``, primary or not.

	The calendar gives a typed attendee a Contact before it saves the event. It
	looked one up on ``Contact.email_id``, which holds the primary address only,
	so a person invited at their second address got a second Contact. This reads
	the address rows themselves, and prefers the contact it is primary on.

	Through ``get_list``, so it answers for the contacts the caller's own list
	shows and no others: a contact at another rep's customer is not found here,
	or an address would be a way to ask whether a colleague's customer has it.
	"""
	email = (email or "").strip()
	if not email:
		return None
	found = frappe.get_list(
		"Contact",
		filters=[["Contact Email", "email_id", "=", email]],
		fields=["name"],
		order_by="`tabContact Email`.`is_primary` desc, `tabContact`.`creation` asc",
		limit_page_length=1,
	)
	return found[0].name if found else None


@frappe.whitelist()
def search_emails(txt: str):
	doctype = "Contact"
	meta = frappe.get_meta(doctype)
	filters = [["Contact", "email_id", "is", "set"]]

	if meta.get("fields", {"fieldname": "enabled", "fieldtype": "Check"}):
		filters.append([doctype, "enabled", "=", 1])
	if meta.get("fields", {"fieldname": "disabled", "fieldtype": "Check"}):
		filters.append([doctype, "disabled", "!=", 1])

	or_filters = []
	search_fields = ["full_name", "email_id", "name"]
	if txt:
		for f in search_fields:
			or_filters.append([doctype, f.strip(), "like", f"%{txt}%"])

	results = frappe.get_list(
		doctype,
		filters=filters,
		fields=search_fields,
		or_filters=or_filters,
		limit_start=0,
		limit_page_length=20,
		order_by="email_id, full_name, name",
		ignore_permissions=False,
		as_list=True,
		strict=False,
	)

	return results


# --- possible duplicates -------------------------------------------------------

DUPLICATE_PAGE_MAX = 50
MERGE_MAX = 20
ERP_IDENTITY = ("acumatica_id", "acumatica_noteid")


def _require_manager() -> None:
	from crm.permissions.customers import is_manager

	if not is_manager():
		frappe.throw(_("Only a manager can review duplicate contacts."), frappe.PermissionError)


def _email_pairs_sql() -> str:
	"""(normalised address, contact) for every address on a Contact the caller
	can read: an in-tree manager reviews their own team's contacts only."""
	from crm.permissions.customers import get_contact_permission_query_conditions

	visible = get_contact_permission_query_conditions(frappe.session.user)
	scope = (
		f"and p.contact in (select `tabContact`.name from `tabContact` where {visible})".replace("%", "%%")
		if visible
		else ""
	)
	return f"""
		select p.k, p.contact from (
			select lower(trim(ce.email_id)) as k, c.name as contact
			from `tabContact Email` ce join `tabContact` c on c.name = ce.parent
			where ce.parenttype = 'Contact' and ifnull(ce.email_id, '') != ''
			union
			select lower(trim(c.email_id)), c.name from `tabContact` c where ifnull(c.email_id, '') != ''
		) p
		where p.k != '' {scope}"""


@frappe.whitelist()
def get_duplicate_contacts(start: int = 0, page_length: int = 20) -> dict:
	"""Contacts that share an email address, a page of addresses at a time.

	Managers only: a group names every rep's customers. One a rep may not read
	is left out for a manager scoped to their team."""
	_require_manager()
	start = max(frappe.utils.cint(start), 0)
	page_length = min(max(frappe.utils.cint(page_length), 1), DUPLICATE_PAGE_MAX)
	pairs = _email_pairs_sql()
	groups = f"select d.k, count(distinct d.contact) as n from ({pairs}) d group by d.k having n > 1"
	# with a value, always: the scope's %% is unescaped only when there is one
	total = frappe.db.sql(f"select count(*) from ({groups}) g where %(on)s", {"on": 1})[0][0]
	page = frappe.db.sql(f"{groups} order by d.k limit %s offset %s", (page_length, start), as_dict=True)
	if not page:
		return {"total": total, "groups": []}

	keys = tuple(row.k for row in page)
	members = frappe.db.sql(
		f"select distinct d.k, d.contact from ({pairs}) d where d.k in %(keys)s", {"keys": keys}
	)
	names = sorted({contact for _k, contact in members})
	contacts = {
		c.name: c
		for c in frappe.get_all(
			"Contact",
			filters={"name": ("in", names)},
			fields=["name", "full_name", "company_name", "email_id", "mobile_no", "owner", "creation"],
		)
	}
	companies = sorted({c.company_name for c in contacts.values() if c.company_name})
	customer_owner = {}
	if companies:
		for org in frappe.get_all(
			"CRM Organization",
			or_filters={"name": ("in", companies), "organization_name": ("in", companies)},
			fields=["name", "organization_name", "account_owner"],
		):
			customer_owner.setdefault(org.organization_name, org.account_owner)
			customer_owner[org.name] = org.account_owner

	from pypika.functions import Count

	Row = frappe.qb.DocType("CRM Contacts")
	deals = dict(
		frappe.qb.from_(Row)
		.select(Row.contact, Count(Row.parent).distinct())
		.where((Row.parenttype == "CRM Deal") & Row.contact.isin(names))
		.groupby(Row.contact)
		.run()
	)

	by_key: dict[str, list] = {}
	for key, name in members:
		contact = contacts.get(name)
		if not contact:
			continue
		by_key.setdefault(key, []).append(
			{
				**contact,
				"customer_owner": customer_owner.get(contact.company_name),
				"deals": deals.get(name, 0),
			}
		)
	return {
		"total": total,
		"groups": [
			{"email": key, "contacts": sorted(by_key.get(key, []), key=lambda c: (c["creation"], c["name"]))}
			for key in keys
		],
	}


def _writable_contact(name):
	if (
		not isinstance(name, str)
		or not name
		or not frappe.db.exists("Contact", name)
		or not frappe.has_permission("Contact", "write", doc=name)
	):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return frappe.get_doc("Contact", name)


def _email_keys(contact) -> set[str]:
	keys = {(row.email_id or "").strip().lower() for row in contact.email_ids}
	keys.add((contact.email_id or "").strip().lower())
	keys.discard("")
	return keys


@frappe.whitelist(methods=["POST"])
def merge_duplicate_contacts(target: str, sources: list | str) -> str:
	"""Merge ``sources`` into ``target``, with frappe's rename-and-merge: every
	link to a source -- deal rows, event participants and attendees, call logs,
	communications -- is moved to the target before the source is deleted.

	Managers only, with write on every contact named, and only contacts that
	share an address with the target: this is for the duplicates list, not a
	general way to fold one person into another."""
	from frappe.model.rename_doc import rename_doc

	_require_manager()
	if isinstance(sources, str):
		sources = frappe.parse_json(sources)
	if not isinstance(sources, list) or not sources or len(sources) > MERGE_MAX:
		frappe.throw(_("Choose between 1 and {0} contacts to merge.").format(MERGE_MAX))
	sources = list(dict.fromkeys(s for s in sources if s != target))
	if not sources:
		frappe.throw(_("Choose a contact other than the one being kept."))

	kept = _writable_contact(target)
	shared = _email_keys(kept)
	merging = [_writable_contact(source) for source in sources]
	for source in merging:
		if not _email_keys(source) & shared:
			frappe.throw(_("{0} does not share an email address with {1}.").format(source.name, kept.name))
		for field in ERP_IDENTITY:
			if source.get(field) and source.get(field) != kept.get(field):
				frappe.throw(
					_(
						"{0} is linked to Acumatica and {1} is not the same contact there. Keep {0} and merge the others into it."
					).format(source.name, kept.name)
				)

	for source in merging:
		_carry_over(source, kept)
		kept.save()
		# checked above: a manager, with write on both, merging a duplicate. The
		# delete it ends in is the merge itself, and loses nothing it points at.
		rename_doc(
			doctype="Contact",
			old=source.name,
			new=kept.name,
			merge=True,
			show_alert=False,
			ignore_permissions=True,
		)
		kept = frappe.get_doc("Contact", kept.name)
	_drop_repeated_deal_rows(kept.name)
	return kept.name


def _carry_over(source, kept) -> None:
	"""The source's addresses, numbers and links the kept contact lacks: the merge
	deletes the source with its child rows."""
	emails = _email_keys(kept)
	for row in source.email_ids:
		key = (row.email_id or "").strip().lower()
		if key and key not in emails:
			kept.append("email_ids", {"email_id": row.email_id, "is_primary": 0})
			emails.add(key)
	phones = {(row.phone or "").strip() for row in kept.phone_nos}
	for row in source.phone_nos:
		phone = (row.phone or "").strip()
		if phone and phone not in phones:
			kept.append("phone_nos", {"phone": row.phone, "is_primary_phone": 0, "is_primary_mobile_no": 0})
			phones.add(phone)
	links = {(row.link_doctype, row.link_name) for row in kept.links}
	for row in source.links:
		if (row.link_doctype, row.link_name) not in links:
			kept.append("links", {"link_doctype": row.link_doctype, "link_name": row.link_name})
			links.add((row.link_doctype, row.link_name))


def _drop_repeated_deal_rows(contact: str) -> None:
	"""A deal that had both contacts now lists the kept one twice."""
	seen = set()
	for row in frappe.get_all(
		"CRM Contacts",
		filters={"contact": contact},
		fields=["name", "parenttype", "parent"],
		order_by="is_primary desc, idx asc",
	):
		if (row.parenttype, row.parent) in seen:
			frappe.db.delete("CRM Contacts", row.name)
		else:
			seen.add((row.parenttype, row.parent))
