"""Customers belong to a rep, and one rep cannot reach another's.

A CRM Organization's ``account_owner`` is the rep whose customer it is. A rep
sees an organization when any of these holds:

- it is theirs (an in-tree manager: theirs or their team's);
- nobody owns it yet -- unclaimed accounts stay open, so prospecting works;
- they have a deal on it they can already read, or planned a visit to it.

Everything else is hidden from the list, the link pickers, search and the
record itself, and so are the contacts that work there. The last condition is
not a way round the first: a rep cannot put a deal or a planned visit on a
customer they cannot see (:func:`assert_customer_allowed`), and the ToDo route
onto someone else's deal is closed in ``crm.api.todo``.

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


def scope_applies(user: str | None = None) -> bool:
	"""Whether ``user``'s customers are narrowed at all."""
	user = user or frappe.session.user
	if sees_everything(user):
		return False
	from crm.api.access import reps_see_all_customers

	return not reps_see_all_customers()


def _in_tree(user: str) -> bool:
	return hierarchy_enabled() and _in_hierarchy(user)


def _is_user(column, user: str, in_tree: bool):
	"""``column`` names ``user`` -- or, for an in-tree manager, anyone on their team."""
	cond = column == user
	return cond | column.isin(_team_mem_query(user)) if in_tree else cond


def visible_organization_condition(user: str | None = None):
	"""The pypika criterion over ``tabCRM Organization`` for ``user``, or None
	when they see every customer."""
	user = user or frappe.session.user
	if not scope_applies(user):
		return None

	in_tree = _in_tree(user)
	Org = frappe.qb.DocType("CRM Organization")
	owner = Org.account_owner

	# The deal half reuses the deal list's own rule, so "a deal I can read" here
	# means exactly what it means on the Deals page.
	Deal = frappe.qb.DocType("CRM Deal")
	deal_cond = _permission_query_conditions(user, "CRM Deal")
	dealt = frappe.qb.from_(Deal).select(Deal.organization).where(Deal.organization.isnotnull())
	if deal_cond:
		dealt = dealt.where(deal_cond)

	Item = frappe.qb.DocType("CRM Rep Plan Item").as_("_cust_item")
	Plan = frappe.qb.DocType("CRM Rep Plan").as_("_cust_plan")
	visited = (
		frappe.qb.from_(Item)
		.join(Plan)
		.on(Item.parent == Plan.name)
		.select(Item.organization)
		.where(Item.organization.isnotnull() & _is_user(Plan.user, user, in_tree))
	)

	return (
		owner.isnull()
		| (owner == "")
		| _is_user(owner, user, in_tree)
		| Org.name.isin(dealt)
		| Org.name.isin(visited)
	)


def visible_contact_condition(user: str | None = None):
	"""Contacts at a customer the user cannot see are hidden with it.

	``company_name`` is free text, so a contact whose company names no
	organization at all stays visible, as does one the user created.
	"""
	user = user or frappe.session.user
	org_cond = visible_organization_condition(user)
	if org_cond is None:
		return None
	Org = frappe.qb.DocType("CRM Organization")
	Contact = frappe.qb.DocType("Contact")
	hidden = frappe.qb.from_(Org).select(Org.name).where(~org_cond)
	return (
		(Contact.owner == user)
		| Contact.company_name.isnull()
		| (Contact.company_name == "")
		| Contact.company_name.notin(hidden)
	)


def _sql(cond) -> str:
	return cond.get_sql(with_namespace=True, quote_char="`", secondary_quote_char="'") if cond else ""


def get_organization_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_organization_condition(user))


def get_contact_permission_query_conditions(user=None, doctype=None):
	return _sql(visible_contact_condition(user))


def _row_visible(doctype: str, name: str, cond) -> bool:
	DT = frappe.qb.DocType(doctype)
	return bool(frappe.qb.from_(DT).select(DT.name).where(DT.name == name).where(cond).limit(1).run())


def has_organization_permission(doc, ptype=None, user=None, debug=False):
	if ptype == "create" or not doc.name or doc.is_new():
		return True
	cond = visible_organization_condition(user)
	return True if cond is None else _row_visible("CRM Organization", doc.name, cond)


def has_contact_permission(doc, ptype=None, user=None, debug=False):
	if ptype == "create" or not doc.name or doc.is_new():
		return True
	cond = visible_contact_condition(user)
	return True if cond is None else _row_visible("Contact", doc.name, cond)


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
	"""Only a manager moves a customer between reps, and an in-tree manager only
	within their own team.

	The field is permlevel 1 (reps read it, managers write it), which already
	makes a rep's edit a no-op; this is the explicit answer for any path that
	writes it directly, and the team rule permlevels cannot express.
	"""
	if doc.is_new() or not doc.has_value_changed("account_owner"):
		return
	user = frappe.session.user
	if sees_everything(user):
		return
	if not is_manager(user):
		frappe.throw(_("Only a manager can change a customer's account owner."), frappe.PermissionError)
	new_owner = doc.account_owner
	if not new_owner or new_owner == user or not _in_tree(user):
		return
	team = {row[0] for row in _team_mem_query(user).run()}
	if new_owner not in team:
		frappe.throw(
			_("{0} is not on your team, so you cannot give them this customer.").format(new_owner),
			frappe.PermissionError,
		)
