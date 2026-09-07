# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

INVITABLE_ROLES = ("Sales User", "Sales Manager", "System Manager")
# Only a System Manager may hand out either of these; a Sales Manager invites reps.
ELEVATED_ROLES = ("Sales Manager", "System Manager")
KEY_LENGTH = 32


def hash_key(raw_key: str) -> str:
	"""What the table stores for an invitation key.

	The raw key travels only in the emailed link. Storing its SHA-256 means a read
	of the row -- a report, an export, a permission gap like the one that let every
	Sales User list pending invitations until 2026-09 -- yields nothing that can be
	pasted into ``accept_invitation``.
	"""
	return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class CRMInvitation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		accepted_at: DF.Datetime | None
		email: DF.Data
		email_sent_at: DF.Datetime | None
		invited_by: DF.Link | None
		key: DF.Data | None
		role: DF.Literal["", "Sales User", "Sales Manager", "System Manager"]
		status: DF.Literal["", "Pending", "Accepted", "Expired"]
	# end: auto-generated types

	def before_insert(self):
		frappe.utils.validate_email_address(self.email, True)
		self.validate_inviter_may_grant_role()

		# The raw key is kept on the instance only long enough to be mailed.
		self._raw_key = frappe.generate_hash(length=KEY_LENGTH)
		self.key = hash_key(self._raw_key)
		self.invited_by = frappe.session.user
		self.status = "Pending"

	def validate_inviter_may_grant_role(self):
		"""The role an invitation grants is bounded by the inviter's own.

		``crm.api.invite_by_email`` checks this too, but the endpoint is not the
		only door: ``frappe.client.insert`` reaches the controller directly, and a
		Sales Manager could insert a System Manager invitation, read its key back
		and accept it as themselves. The check belongs where every insert passes.
		"""
		if self.role not in INVITABLE_ROLES:
			frappe.throw(_("Cannot invite for this role"), frappe.PermissionError)
		if self.role in ELEVATED_ROLES and "System Manager" not in frappe.get_roles(frappe.session.user):
			frappe.throw(
				_("Only a System Manager can invite a {0}").format(_(self.role)),
				frappe.PermissionError,
			)

	def after_insert(self):
		self.invite_via_email()

	def invite_via_email(self):
		raw_key = getattr(self, "_raw_key", None)
		if not raw_key:
			# A resend: the stored value is a hash and cannot be turned back into a
			# link, so the invitation gets a fresh key and the old link dies.
			raw_key = frappe.generate_hash(length=KEY_LENGTH)
			self.db_set("key", hash_key(raw_key))
		invite_link = frappe.utils.get_url(f"/api/method/crm.api.accept_invitation?key={raw_key}")
		if frappe.local.dev_server:
			print(f"Invite link for {self.email}: {invite_link}")  # nosemgrep

		# The site's own brand when an admin set one, which is the whole point of
		# the Brand settings page. This is the first email a new user receives, so
		# it is the worst place for the product to call itself something other
		# than what the rest of their CRM says.
		title = frappe.db.get_single_value("FCRM Settings", "brand_name") or "Vectora"
		template = "crm_invitation"

		frappe.sendmail(
			recipients=self.email,
			subject=_("You have been invited to join {0}").format(title),
			template=template,
			args={"title": title, "invite_link": invite_link},
			now=True,
		)
		self.db_set("email_sent_at", frappe.utils.now())

	@frappe.whitelist()
	def accept_invitation(self):
		# Accepting on the invitee's behalf creates their account and mails them a
		# set-password link. That is an administrator's act: a Sales Manager who
		# could do it would be creating accounts, including for roles above their own.
		frappe.only_for("System Manager", True)
		if self.accept():
			# the invitee was not around to set a password, mail them a link to do it
			frappe.get_doc("User", self.email).send_welcome_mail_to_user()

	def accept(self):
		if self.status != "Pending":
			frappe.throw(_("Invalid or expired key"))

		user, is_new_user = self.create_user_if_not_exists()
		user.append_roles(self.role)
		if self.role == "System Manager":
			user.append_roles("Sales Manager", "Sales User")
		elif self.role == "Sales Manager":
			user.append_roles("Sales User")
		if self.role == "Sales User":
			self.update_module_in_user(user, "FCRM")
		user.save(ignore_permissions=True)

		self.status = "Accepted"
		self.accepted_at = frappe.utils.now()
		self.key = None
		self.save(ignore_permissions=True)

		return is_new_user

	def update_module_in_user(self, user, module):
		block_modules = frappe.get_all(
			"Module Def",
			fields=["name as module"],
			filters={"name": ["!=", module]},
		)

		if block_modules:
			user.set("block_modules", block_modules)

	def create_user_if_not_exists(self):
		if not frappe.db.exists("User", self.email):
			first_name = self.email.split("@")[0].title()
			user = frappe.get_doc(
				doctype="User",
				user_type="System User",
				email=self.email,
				send_welcome_email=0,
				first_name=first_name,
				default_app="crm",
			).insert(ignore_permissions=True)
			return user, True

		return frappe.get_doc("User", self.email), False


def expire_invitations():
	"""expire invitations after 3 days"""
	from frappe.utils import add_days, now

	days = 3
	invitations_to_expire = frappe.db.get_all(
		"CRM Invitation", filters={"status": "Pending", "creation": ["<", add_days(now(), -days)]}
	)
	for invitation in invitations_to_expire:
		# Isolated per row: one invitation that will not save (a validation it
		# no longer passes, a user row gone) must not stop the rest expiring.
		frappe.db.savepoint("crm_invitation_expire")
		try:
			doc = frappe.get_doc("CRM Invitation", invitation.name)
			doc.status = "Expired"
			doc.save(ignore_permissions=True)
		except Exception:
			frappe.db.rollback(save_point="crm_invitation_expire")
			frappe.log_error(
				title="CRM Invitation: expiry failed",
				message=f"{invitation.name}: {frappe.get_traceback()}",
			)


def get_permission_query_conditions(user=None):
	"""Managers see the invitations they sent; System Managers see them all.

	Reps have no read grant at all any more. This is the list door
	(``frappe.client.get_list``, report view, export); ``has_permission`` below is
	the record door, and the two must agree.
	"""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"`tabCRM Invitation`.`invited_by` = {frappe.db.escape(user)}"


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return True
	if ptype in ("create", "write"):
		# invitations are created through crm.api.invite_by_email, which checks the
		# inviter's role and inserts on their behalf
		return False
	return doc.invited_by == user
