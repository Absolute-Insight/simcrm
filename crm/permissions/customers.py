"""Customers belong to a rep, and one rep cannot reach another's.

A CRM Organization's ``account_owner`` is the rep whose customer it is. A rep
sees an organization when any of these holds:

- it is theirs (an in-tree manager: theirs or their team's);
- nobody owns it yet -- unclaimed accounts stay open, so prospecting works;
- they have a deal on it they can already read, or planned a visit to it.

Everything else is hidden from the list, the link pickers, search and the
record itself, and so are what would name it from the side: the contacts that
work there, its addresses, its enrichment runs and events with it as a
participant. The last condition is not a way round the first: a rep cannot put a
deal or a planned visit on a customer they cannot see, nor a contact there on a
deal (:func:`assert_customer_allowed`, :func:`assert_contact_allowed`), and the
ToDo route onto someone else's deal is closed in ``crm.api.todo``. It also lets
them read the customer only: editing, sharing and renaming it take the first two.

Leads are deliberately not a source of visibility: a lead's ``organization`` is
free text, so a rep could type a colleague's customer into one.

Administrators, System Managers and out-of-tree managers who see every record
see every customer. CRM Access Settings ``rep_customer_scope`` set to
"All customers" switches the whole rule off.
"""

from __future__ import annotations

import frappe
from frappe import _

from crm.permissions.org_hierarchy import (
	_in_hierarchy,
	_permission_query_conditions,
	_team_mem_query,
	hierarchy_enabled,
	sees_everything,
)

MANAGER_ROLES = ("Sales Manager", "System Manager")
#: What a deal or a visit at a customer entitles a rep to. Anything else (write,
#: share, delete) needs the customer to be theirs or nobody's: frappe's shares
#: override the query condition, so a share would open it to every rep.
READ_PTYPES = ("read", "select", "print", "email", "export", "report")


def scope_applies(user: str | None = None) -> bool:
	"""Whether ``user``'s customers are narrowed at all."""
	user = user or frappe.session.user
	# Guest reaches an organization only through a public form's link field, by a
	# grant an admin made on purpose; it has no customers of its own to be kept to.
	if user == "Guest" or sees_everything(user):
		return False
	from crm.api.access import reps_see_all_customers

	return not reps_see_all_customers()


def _in_tree(user: str) -> bool:
	return hierarchy_enabled() and _in_hierarchy(user)


def _is_user(column, user: str, in_tree: bool):
	"""``column`` names ``user`` -- or, for an in-tree manager, anyone on their team."""
	cond = column == user
	return cond | column.isin(_team_mem_query(user)) if in_tree else cond


def visible_organization_condition(user: str | None = None, for_write: bool = False):
	"""The pypika criterion over ``tabCRM Organization`` for ``user``, or None
	when they see every customer. ``for_write`` drops the deal and visit routes."""
	user = user or frappe.session.user
	if not scope_applies(user):
		return None

	in_tree = _in_tree(user)
	Org = frappe.qb.DocType("CRM Organization")
	owner = Org.account_owner
	held = owner.isnull() | (owner == "") | _is_user(owner, user, in_tree)
	if for_write:
		return held

	Item = frappe.qb.DocType("CRM Rep Plan Item").as_("_cust_item")
	Plan = frappe.qb.DocType("CRM Rep Plan").as_("_cust_plan")
	visited = (
		frappe.qb.from_(Item)
		.join(Plan)
		.on(Item.parent == Plan.name)
		.select(Item.organization)
		.where(Item.organization.isnotnull() & _is_user(Plan.user, user, in_tree))
	)
	Deal = frappe.qb.DocType("CRM Deal")
	dealt = _readable_deals(user, Deal.organization).where(Deal.organization.isnotnull())
	return held | Org.name.isin(dealt) | Org.name.isin(visited)


def _readable_deals(user: str, column):
	"""``column`` of the deals ``user`` can read, by the Deals page's own rule."""
	Deal = frappe.qb.DocType("CRM Deal")
	query = frappe.qb.from_(Deal).select(column)
	deal_cond = _permission_query_conditions(user, "CRM Deal")
	return query.where(deal_cond) if deal_cond else query


def _hidden_organizations(org_cond, column="name"):
	Org = frappe.qb.DocType("CRM Organization")
	# isnotnull: one NULL in a NOT IN subquery makes the whole test NULL, and every
	# contact would vanish with it
	return frappe.qb.from_(Org).select(Org[column]).where(Org[column].isnotnull()).where(~org_cond)


def visible_contact_condition(user: str | None = None, for_write: bool = False):
	"""Contacts at a customer the user cannot see are hidden with it.

	``company_name`` is free text, so it is matched on the display name as well as
	the docname, which differ for a customer named after its code. A contact whose
	company names no organization stays visible, as does one the user created or
	one on a deal they can read. ``for_write`` holds the contact to the customer
	being theirs, as for the customer itself: a deal there gives read only.
	"""
	user = user or frappe.session.user
	org_cond = visible_organization_condition(user, for_write)
	if org_cond is None:
		return None
	Contact = frappe.qb.DocType("Contact")
	cond = (
		(Contact.owner == user)
		| Contact.company_name.isnull()
		| (Contact.company_name == "")
		| (
			Contact.company_name.notin(_hidden_organizations(org_cond))
			& Contact.company_name.notin(_hidden_organizations(org_cond, "organization_name"))
		)
	)
	if for_write:
		return cond
	Row = frappe.qb.DocType("CRM Contacts").as_("_cust_row")
	Deal = frappe.qb.DocType("CRM Deal")
	on_my_deal = (
		frappe.qb.from_(Row)
		.select(Row.contact)
		# isnotnull: this is negated for events, and one blank row in a NOT over an IN
		# would make every contact look visible there
		.where(
			Row.contact.isnotnull()
			& (Row.parenttype == "CRM Deal")
			& Row.parent.isin(_readable_deals(user, Deal.name))
		)
	)
	return cond | Contact.name.isin(on_my_deal)


def visible_address_condition(user: str | None = None, for_write: bool = False):
	"""An address names its customer, and the import titles it with the name."""
	user = user or frappe.session.user
	org_cond = visible_organization_condition(user, for_write)
	if org_cond is None:
		return None
	Address = frappe.qb.DocType("Address")
	Link = frappe.qb.DocType("Dynamic Link").as_("_cust_link")
	Org = frappe.qb.DocType("CRM Organization")
	linked = (
		frappe.qb.from_(Link)
		.select(Link.parent)
		.where(
			(Link.parenttype == "Address")
			& (Link.link_doctype == "CRM Organization")
			& Link.link_name.isin(_hidden_organizations(org_cond))
		)
	)
	on_record = frappe.qb.from_(Org).select(Org.address).where(Org.address.isnotnull()).where(~org_cond)
	return (Address.owner == user) | (Address.name.notin(linked) & Address.name.notin(on_record))


def visible_event_condition(user: str | None = None):
	"""Calendar events are Public by default, and they name the customer: by a
	participant, or by the record they were added from, which is where a subject and
	a location come along. A rep keeps their own, and those they attend."""
	user = user or frappe.session.user
	org_cond = visible_organization_condition(user)
	if org_cond is None:
		return None
	Event = frappe.qb.DocType("Event")
	Part = frappe.qb.DocType("Event Participants").as_("_cust_part")
	Other = frappe.qb.DocType("Event").as_("_cust_event")
	Contact = frappe.qb.DocType("Contact")
	Deal = frappe.qb.DocType("CRM Deal")
	hidden_orgs = _hidden_organizations(org_cond)
	hidden_contacts = frappe.qb.from_(Contact).select(Contact.name).where(~visible_contact_condition(user))
	deals_there = frappe.qb.from_(Deal).select(Deal.name).where(Deal.organization.isin(hidden_orgs))

	def names_hidden(doctype_field, name_field):
		return ((doctype_field == "CRM Organization") & name_field.isin(hidden_orgs)) | (
			(doctype_field == "Contact") & name_field.isin(hidden_contacts)
		)

	by_participant = (
		frappe.qb.from_(Part)
		.select(Part.parent)
		.where((Part.parenttype == "Event") & names_hidden(Part.reference_doctype, Part.reference_docname))
	)
	# a subquery, not a bare NOT: most events have no reference, and NOT NULL is NULL
	by_reference = (
		frappe.qb.from_(Other)
		.select(Other.name)
		.where(
			names_hidden(Other.reference_doctype, Other.reference_docname)
			| ((Other.reference_doctype == "CRM Deal") & Other.reference_docname.isin(deals_there))
		)
	)
	attending = (
		frappe.qb.from_(Part).select(Part.parent).where((Part.parenttype == "Event") & (Part.email == user))
	)
	return (
		(Event.owner == user)
		| (Event.name.notin(by_participant) & Event.name.notin(by_reference))
		| Event.name.isin(attending)
	)


def _sql(cond) -> str:
	return cond.get_sql(with_namespace=True, quote_char="`", secondary_quote_char="'") if cond else ""


def get_organization_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_organization_condition(user))


def get_contact_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_contact_condition(user))


def get_address_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_address_condition(user))


def get_event_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_event_condition(user))


def _row_visible(doctype: str, name: str, cond) -> bool:
	DT = frappe.qb.DocType(doctype)
	return bool(frappe.qb.from_(DT).select(DT.name).where(DT.name == name).where(cond).limit(1).run())


def has_organization_permission(doc, ptype=None, user=None, debug=False):
	if ptype == "create" or not doc.name or doc.is_new():
		return True
	cond = visible_organization_condition(user, for_write=ptype not in READ_PTYPES)
	return True if cond is None else _row_visible("CRM Organization", doc.name, cond)


def _has_row_permission(doc, ptype, doctype, condition, user, **kwargs) -> bool:
	if ptype == "create" or not doc.name or doc.is_new():
		return True
	cond = condition(user, **kwargs)
	return True if cond is None else _row_visible(doctype, doc.name, cond)


def has_contact_permission(doc, ptype=None, user=None, debug=False):
	return _has_row_permission(
		doc, ptype, "Contact", visible_contact_condition, user, for_write=ptype not in READ_PTYPES
	)


def has_address_permission(doc, ptype=None, user=None, debug=False):
	return _has_row_permission(
		doc, ptype, "Address", visible_address_condition, user, for_write=ptype not in READ_PTYPES
	)


def has_event_permission(doc, ptype=None, user=None, debug=False):
	return _has_row_permission(doc, ptype, "Event", visible_event_condition, user)


def customer_visible(organization: str, user: str | None = None) -> bool:
	cond = visible_organization_condition(user)
	return True if cond is None else _row_visible("CRM Organization", organization, cond)


def assert_customer_allowed(organization: str | None, user: str | None = None) -> None:
	"""Refuse to attach a record to a customer the user cannot see.

	Link validation only checks the organization exists, and a name is easy to
	type, so without this a rep could open a deal or plan a visit on a
	colleague's customer -- and the deal would then make the customer visible to
	them. The message does not say whose customer it is.
	"""
	if not organization:
		return
	user = user or frappe.session.user
	if customer_visible(organization, user):
		return
	frappe.throw(
		_("{0} is another rep's customer. Ask a manager to reassign it to you.").format(organization),
		frappe.PermissionError,
	)


def assert_contact_allowed(contact: str | None, user: str | None = None) -> None:
	"""Refuse to attach a contact the user cannot see to a deal or a lead.

	A deal's contact rows are read back with no permission check of their own, so
	attaching one was a way to read it: its name, email and mobile come with it.
	"""
	if not contact:
		return
	cond = visible_contact_condition(user or frappe.session.user)
	if cond is None or _row_visible("Contact", contact, cond):
		return
	frappe.throw(
		_("This contact is at another rep's customer. Ask a manager to reassign it to you."),
		frappe.PermissionError,
	)


def validate_event_participants(doc, method=None) -> None:
	"""An Event's save fills a participant's email in with no permission check, so
	naming a hidden contact, or a hidden customer's default one, was a way to read it.
	Only rows that are new here are checked: an old event stays editable after its
	customer moves. Server code that books on a rep's behalf is trusted, as it is
	past a higher permlevel."""
	if doc.flags.ignore_permissions or not scope_applies():
		return
	before = doc.get_doc_before_save()
	stored = (
		{(row.reference_doctype, row.reference_docname) for row in before.event_participants}
		if before
		else set()
	)
	for row in doc.event_participants:
		# a stored row with no email yet is still to be filled in, so it is no
		# evidence the rep could already read that person's address
		if row.email and (row.reference_doctype, row.reference_docname) in stored:
			continue
		if row.reference_doctype == "Contact":
			assert_contact_allowed(row.reference_docname)
		elif row.reference_doctype == "CRM Organization":
			assert_customer_allowed(row.reference_docname)


def refuse_direct_participant_save(doc, method=None) -> None:
	"""A participant is saved with its event, never on its own.

	frappe runs this only when the row itself is saved, so a row written directly
	was in the database, and so looked stored, by the time the event's own check
	came to it. The CRM never writes a participant this way."""
	if doc.flags.ignore_permissions or not scope_applies():
		return
	frappe.throw(_("A participant is saved with their event, not on their own."), frappe.PermissionError)


@frappe.whitelist()
def get_events(
	start: str,
	end: str,
	user: str | None = None,
	for_reminder: bool = False,
	filters: str | list | dict | None = None,
):
	"""frappe's calendar feed, less the events a rep may not see.

	It is raw SQL behind its own whitelist, so neither hook reaches it. Stands in for
	``frappe.desk.doctype.event.event.get_events``. The daily event digest reads the
	same query from the scheduler and is not covered: it mails only Public events
	with Send Reminder set, which CRM events do not set.
	"""
	from frappe.desk.doctype.event.event import get_events as frappe_get_events

	events = frappe_get_events(start, end, user=user, for_reminder=for_reminder, filters=filters)
	if not events or not scope_applies():
		return events
	names = list({event.name for event in events})
	allowed = set(
		frappe.get_list("Event", filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	)
	return [event for event in events if event.name in allowed]


def is_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(MANAGER_ROLES))


def can_own_customers(user: str | None) -> bool:
	"""A plain rep. Managers and admins oversee accounts rather than hold them,
	and an account parked on one would hide it from every rep."""
	if not user or user in ("Administrator", "Guest"):
		return False
	roles = set(frappe.get_roles(user))
	return "Sales User" in roles and not roles & set(MANAGER_ROLES)


def claim_if_unowned(organization: str | None, user: str | None) -> None:
	"""Make ``user`` the account owner of an organization nobody owns yet.

	A direct write: the claim is the system's, not the user's edit, and a rep
	does not hold write access to the field.
	"""
	if not organization or not can_own_customers(user):
		return
	if frappe.db.get_value("CRM Organization", organization, "account_owner"):
		return
	frappe.db.set_value("CRM Organization", organization, "account_owner", user, update_modified=False)


def validate_account_owner_change(doc) -> None:
	"""Only a manager moves a customer between reps, and a team's manager only
	within that team.

	The field is permlevel 1 (reps read it, managers write it), which already
	makes a rep's edit a no-op; this is the explicit answer for any path that
	writes it directly, and the team rule permlevels cannot express.
	"""
	if doc.is_new() or not doc.has_value_changed("account_owner"):
		return
	user = frappe.session.user
	if sees_everything(user):
		return
	if not is_manager(user) or not _in_tree(user):
		# a manager scoped to their own records has no team to reassign within
		frappe.throw(_("Only a manager can change a customer's account owner."), frappe.PermissionError)
	team = {row[0] for row in _team_mem_query(user).run()}
	before = doc.get_doc_before_save()
	old_owner = before.account_owner if before else None
	if old_owner and old_owner not in team:
		frappe.throw(_("This customer is not your team's to reassign."), frappe.PermissionError)
	new_owner = doc.account_owner
	if new_owner and (new_owner not in team or not can_own_customers(new_owner)):
		frappe.throw(
			_("{0} is not a rep on your team, so you cannot give them this customer.").format(new_owner),
			frappe.PermissionError,
		)
