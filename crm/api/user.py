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
	"modified",
)
PROFILE_EDITABLE_FIELDS = frozenset({"first_name", "last_name", "user_image", "language", "time_zone"})


def _own_user() -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("You must be logged in"), frappe.AuthenticationError)
	return user


@frappe.whitelist()
def get_profile() -> dict:
	"""The session user's own profile, readable regardless of User doctype grants."""
	return frappe.db.get_value("User", _own_user(), list(PROFILE_FIELDS), as_dict=True)


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
		doc.set(field, value)
	doc.save(ignore_permissions=True)
	return get_profile()


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

	if new_role == "Sales Manager" and not is_system_manager:
		frappe.throw(_("Only System Managers can assign the Sales Manager role"), frappe.PermissionError)

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

	if user_doc.get("role_profiles") or user_doc.get("role_profile_name"):
		return frappe.throw(
			_("User {0} cannot be removed as it has a Role Profile assigned to it.").format(user)
		)

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
