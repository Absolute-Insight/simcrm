import frappe
from frappe import _
from frappe.auth import LoginAttemptTracker
from frappe.rate_limiter import rate_limit
from frappe.utils.password import check_password, update_password

# What Settings -> Profile and Settings -> Preferences show and let a person change
# about themselves. frappe's User doctype grants read and write to System Manager
# only (plus `select` to Desk User), so the frappe.client document resource the
# panes used answered 403 for every Sales User: a rep could not see their own
# name, change their photo, or pick a language. These two endpoints are the
# rep's own row, nothing else, through an allow-list of fields.
PROFILE_FIELDS = (
	"name",
	"email",
	"first_name",
	"last_name",
	"full_name",
	"user_image",
	"language",
	"time_zone",
	"email_signature",
	"modified",
)
PROFILE_EDITABLE_FIELDS = frozenset(
	{"first_name", "last_name", "user_image", "language", "time_zone", "email_signature", "user_emails"}
)
# The child rows a person may set: which outgoing accounts they may send from.
USER_EMAIL_FIELDS = ("email_account", "email_id")


def _own_user() -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("You must be logged in"), frappe.AuthenticationError)
	return user


@frappe.whitelist()
def get_profile() -> dict:
	"""The session user's own profile, readable regardless of User doctype grants."""
	user = _own_user()
	profile = frappe.db.get_value("User", user, list(PROFILE_FIELDS), as_dict=True)
	profile["user_emails"] = _user_emails(user)
	return profile


def _user_emails(user: str) -> list[dict]:
	"""The child rows the email composer and the signature pane read.

	``enable_outgoing`` comes from the account, not from the row's copy of it: frappe
	only refreshes that copy for an account whose address is a user's, so a shared
	mailbox would go on being offered as a sender after its outgoing was turned off.
	"""
	row = frappe.qb.DocType("User Email")
	account = frappe.qb.DocType("Email Account")
	return (
		frappe.qb.from_(row)
		.left_join(account)
		.on(row.email_account == account.name)
		.select(row.email_account, row.email_id, account.enable_outgoing)
		.where((row.parent == user) & (row.parenttype == "User"))
		.orderby(row.idx)
		.run(as_dict=True)
	)


@frappe.whitelist(methods=["POST"])
def update_profile(changes: dict | str) -> dict:
	"""Change the session user's own profile fields; anything else is refused.

	Saved with ``ignore_permissions`` because the row is the caller's own and the
	field list is fixed here -- roles, email, enabled and everything that grants
	access are not in it and cannot be reached through this door.
	"""
	user = _own_user()
	changes = frappe.parse_json(changes) if isinstance(changes, str) else (changes or {})
	unknown = set(changes) - PROFILE_EDITABLE_FIELDS
	if unknown:
		frappe.throw(
			_("These fields cannot be changed here: {0}").format(", ".join(sorted(unknown))),
			frappe.ValidationError,
		)
	doc = frappe.get_doc("User", user)
	for field, value in changes.items():
		if field == "user_emails":
			# rows are rebuilt from the two fields the UI knows; anything else a
			# client might send on a row is dropped, and the Link validation on
			# User Email still refuses an account that does not exist
			rows = value if isinstance(value, list) else frappe.parse_json(value or "[]")
			rows = [{key: (row or {}).get(key) for key in USER_EMAIL_FIELDS} for row in rows]
			_reject_other_peoples_mailboxes(doc, rows)
			doc.set("user_emails", rows)
		else:
			doc.set(field, value)
	doc.save(ignore_permissions=True)
	return get_profile()


def _reject_other_peoples_mailboxes(doc, rows: list[dict]) -> None:
	"""A rep may not link an Email Account that belongs to somebody else.

	These rows are what the composer offers as From, so linking a colleague's
	account advertised their mailbox as a sender -- and this endpoint saves with
	``ignore_permissions``, so nothing else was standing in the way.

	The test is ownership, not self-ownership: an account whose address is
	another *user's* address is refused, while a shared or role mailbox
	(sales@, support@ -- an address no user account answers to) stays
	linkable, which is what those accounts exist for.

	An account that does not exist is left alone: the Link validation on User
	Email refuses it, and with the message that names the real problem.

	Only rows the caller is *adding* are checked, so an administrator may link
	a mailbox from the desk without the owner's next profile save failing on
	it. A System Manager, who can edit any User row anyway, keeps the wider
	choice.
	"""
	if "System Manager" in frappe.get_roles():
		return

	already_linked = {row.email_account for row in doc.get("user_emails") or []}
	own_address = (doc.email or "").strip().lower()
	for row in rows:
		account = row.get("email_account")
		if not account or account in already_linked:
			continue
		address = (frappe.db.get_value("Email Account", account, "email_id") or "").strip().lower()
		if not address or address == own_address:
			continue
		owner = frappe.db.exists("User", {"email": address, "enabled": 1})
		if owner:
			frappe.throw(
				_("Email Account {0} belongs to {1}").format(account, address),
				frappe.PermissionError,
			)


@frappe.whitelist()
@rate_limit(limit=5, seconds=300)  # 5 attempts per 5 minutes per user/IP
def change_password(old_password: str, new_password: str):
	"""
	Change password for the current logged-in user.
	Uses Frappe's LoginAttemptTracker for attempt counting/lockout, and rate_limit for API abuse protection.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("You must be logged in to change your password"), frappe.AuthenticationError)

	tracker = LoginAttemptTracker(user)
	if not tracker.is_user_allowed():
		frappe.throw(_("Too many failed attempts. Please try again after some time."))

	if old_password == new_password:
		frappe.throw(
			_("New password cannot be the same as current password. Please choose a different password.")
		)

	try:
		check_password(user, old_password)
	except frappe.AuthenticationError:
		tracker.add_failure_attempt()
		frappe.throw(_("Incorrect current password. Please try again."))
	else:
		tracker.add_success_attempt()

	# Validate new password strength (server-side enforcement)
	from frappe.core.doctype.user.user import test_password_strength

	result = test_password_strength(new_password)
	feedback = result.get("feedback", {})
	if not feedback.get("password_policy_validation_passed", False):
		suggestions = feedback.get("suggestions", [])
		frappe.throw(_("Password is too weak. {0}").format(" ".join(suggestions) if suggestions else ""))

	update_password(user=user, pwd=new_password, logout_all_sessions=False)
	return _("Password Updated Successfully")


@frappe.whitelist()
def add_existing_users(users: str | list, role: str = "Sales User"):
	"""
	Add existing users to the CRM by assigning them a role (Sales User or Sales Manager).
	:param users: List of user names to be added
	"""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	is_system_manager = "System Manager" in frappe.get_roles()

	if role == "System Manager" and not is_system_manager:
		frappe.throw(_("Only System Managers can assign the System Manager role"), frappe.PermissionError)

	if role == "Sales Manager" and not is_system_manager:
		frappe.throw(_("Only System Managers can assign the Sales Manager role"), frappe.PermissionError)

	users = frappe.parse_json(users)

	for user in users:
		update_user_role(user, role)


@frappe.whitelist()
def update_user_role(user: str, new_role: str):
	"""
	Update the role of the user to Sales Manager, Sales User, or System Manager.
	:param user: The name of the user
	:param new_role: The new role to assign (Sales Manager or Sales User)
	"""

	frappe.only_for(["System Manager", "Sales Manager"], True)
	is_system_manager = "System Manager" in frappe.get_roles()

	if new_role not in ["System Manager", "Sales Manager", "Sales User"]:
		frappe.throw(_("Cannot assign this role"))

	user_doc = frappe.get_doc("User", user)
	target_roles = [d.role for d in user_doc.roles]
	target_is_system_manager = "System Manager" in target_roles

	if new_role == "System Manager" and not is_system_manager:
		frappe.throw(_("Only System Managers can assign the System Manager role"), frappe.PermissionError)

	if target_is_system_manager and not is_system_manager:
		frappe.throw(_("Only System Managers can modify other System Managers"), frappe.PermissionError)

	# The same rule as granting the role: a Sales Manager manages reps, and a
	# peer manager's role is a System Manager's to change. Without this any team
	# lead could demote another to Sales User and lock them out of their team's
	# records.
	if "Sales Manager" in target_roles and not is_system_manager:
		frappe.throw(_("Only System Managers can modify other Sales Managers"), frappe.PermissionError)

	if new_role == "Sales Manager" and not is_system_manager:
		frappe.throw(_("Only System Managers can assign the Sales Manager role"), frappe.PermissionError)

	# Somebody already in the CRM is somebody's rep: a scoped manager changes
	# their own team's, not another manager's. Bringing in an account with no
	# CRM role yet is onboarding -- it is on no team to be outside of.
	if not is_system_manager and set(target_roles) & {"Sales User", "Sales Manager"}:
		from crm.api.quota import _only_own_team

		_only_own_team(user)

	# After the permission checks, as in remove_crm_roles_from_user: a caller
	# who may not touch this user should not learn how their roles are managed.
	validate_no_role_profile(user_doc)

	if new_role == "System Manager":
		user_doc.append_roles("System Manager", "Sales Manager", "Sales User")
		user_doc.set("block_modules", [])
	if new_role == "Sales Manager":
		user_doc.append_roles("Sales Manager", "Sales User")
		remove_roles(user_doc, "System Manager")
	if new_role == "Sales User":
		node = frappe.db.get_value(
			"CRM Sales Hierarchy", {"user": user}, ["name", "reports_to"], as_dict=True
		)
		if node:
			has_reports = frappe.db.exists("CRM Sales Hierarchy", {"reports_to": node.name})
			if has_reports or not node.reports_to:
				frappe.throw(
					_("Remove this user from the sales hierarchy before changing their role to Sales User")
				)
		user_doc.append_roles("Sales User")
		remove_roles(user_doc, "Sales Manager", "System Manager")
		update_module_in_user(user_doc, "FCRM")

	user_doc.save(ignore_permissions=True)


@frappe.whitelist()
def remove_crm_roles_from_user(user: str):
	"""
	Remove a user means removing Sales User & Sales Manager roles from the user.
	:param user: The name of the user to be removed
	"""
	frappe.only_for(["System Manager", "Sales Manager"], True)

	if user == frappe.session.user:
		frappe.throw(_("You cannot remove yourself."), frappe.PermissionError)

	user_doc = frappe.get_doc("User", user)
	roles = [d.role for d in user_doc.roles]

	current_user_is_system_manager = "System Manager" in frappe.get_roles()

	if "System Manager" in roles and not current_user_is_system_manager:
		frappe.throw(_("Only System Managers can modify other System Managers"), frappe.PermissionError)

	if "Sales Manager" in roles and not current_user_is_system_manager:
		frappe.throw(_("Only System Managers can modify other Sales Managers"), frappe.PermissionError)

	# A manager offboards their own reps. Without this an in-tree manager could
	# strip another team's rep of their CRM role and delete their place in the
	# hierarchy -- a node Sales Manager may otherwise only read.
	if not current_user_is_system_manager:
		from crm.api.quota import _only_own_team

		_only_own_team(user)

	validate_no_role_profile(user_doc)

	# Refuse before touching anything. The node delete at the end of this
	# function is what fails when a manager still has reports, and by then the
	# stripped roles have already been saved -- the admin gets a 500 and a user
	# who is half-offboarded. update_role() below already guards this case; this
	# path did not. Same question, asked before the first write instead of after
	# the last one.
	node_name = frappe.db.get_value("CRM Sales Hierarchy", {"user": user}, "name")
	if node_name and frappe.db.exists("CRM Sales Hierarchy", {"reports_to": node_name}):
		frappe.throw(
			_("{0} still has people reporting to them. Move their reports to another manager first.").format(
				user
			)
		)

	if "Sales User" in roles:
		remove_roles(user_doc, "Sales User")
	if "Sales Manager" in roles:
		remove_roles(user_doc, "Sales Manager")
	if "System Manager" in roles and current_user_is_system_manager:
		remove_roles(user_doc, "System Manager")
		update_module_in_user(user_doc, "FCRM")

	user_doc.save(ignore_permissions=True)

	if node_name:
		frappe.delete_doc("CRM Sales Hierarchy", node_name, ignore_permissions=True)

	frappe.msgprint(_("User {0} has been removed from CRM roles.").format(user))


def validate_no_role_profile(user_doc):
	"""
	Throw if the user's roles are governed by a Role Profile.
	User.validate() re-derives `roles` from the assigned Role Profile on every save,
	so any role appended or removed here would be silently reverted.
	"""
	if user_doc.get("role_profiles") or user_doc.get("role_profile_name"):
		frappe.throw(
			_("Roles of user {0} are managed by a Role Profile. Update the Role Profile instead.").format(
				frappe.bold(user_doc.name)
			),
			title=_("Role Profile Assigned"),
		)


def remove_roles(self, *roles):
	existing_roles = {d.role: d for d in self.get("roles")}
	for role in roles:
		if role in existing_roles:
			self.get("roles").remove(existing_roles[role])


def update_module_in_user(user, module):
	block_modules = frappe.get_all(
		"Module Def",
		fields=["name as module"],
		filters={"name": ["!=", module]},
	)

	if block_modules:
		user.set("block_modules", block_modules)
