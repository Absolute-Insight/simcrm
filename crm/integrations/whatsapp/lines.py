"""Who sends from which WhatsApp number, and who a number belongs to.

Every rep has a work number of their own, so an account is a property of the
person: the sender is always derived from the session here and is never taken
from a request.
"""

import frappe
from frappe import _

LINE = "CRM WhatsApp Line"


def _is_active(account: str) -> bool:
	return frappe.db.get_value("WhatsApp Account", account, "status") == "Active"


def get_sending_account(user: str | None = None) -> str | None:
	"""The account ``user`` sends from, or None if they have none.

	Their own line, when active. Otherwise the site's default outgoing account
	if there is one, unless that account is another rep's line: a default must
	not become a way to speak from a colleague's number.
	"""
	if not frappe.db.exists("DocType", "WhatsApp Account"):
		return None
	user = user or frappe.session.user
	own = frappe.db.get_value(LINE, {"user": user}, "whatsapp_account")
	if own:
		return own if _is_active(own) else None

	default = frappe.db.get_single_value("WhatsApp Settings", "default_outgoing_account")
	if not default or not _is_active(default):
		return None
	if frappe.db.get_value(LINE, {"whatsapp_account": default}, "user"):
		return None
	return default


def require_sending_account() -> str:
	account = get_sending_account()
	if not account:
		frappe.throw(
			_("You have no active WhatsApp number. Ask your administrator to add one for you."),
			frappe.ValidationError,
		)
	return account


def get_line_user(account: str | None) -> str | None:
	"""The rep whose number ``account`` is. Every line has one."""
	return frappe.db.get_value(LINE, {"whatsapp_account": account}, "user") if account else None
