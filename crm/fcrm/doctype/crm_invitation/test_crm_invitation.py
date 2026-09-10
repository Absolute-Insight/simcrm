# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now


class TestCRMInvitation(FrappeTestCase):
	def make_invitation(self, email="invitee@example.com", role="Sales User"):
		"""Create a Pending invitation without actually sending an email."""
		with patch.object(frappe, "sendmail"):
			return frappe.get_doc(
				doctype="CRM Invitation",
				email=email,
				role=role,
			).insert(ignore_permissions=True)

	def test_new_invitation_is_pending_with_key(self):
		invitation = self.make_invitation()
		self.assertEqual(invitation.status, "Pending")
		self.assertTrue(invitation.key)
		self.assertEqual(invitation.invited_by, frappe.session.user)

	def test_accept_pending_invitation(self):
		invitation = self.make_invitation()

		invitation.accept()

		self.assertEqual(invitation.status, "Accepted")
		self.assertTrue(invitation.accepted_at)
		self.assertTrue(frappe.db.exists("User", invitation.email))

	def test_accept_clears_key(self):
		"""The key is wiped after acceptance so the invite link cannot be reused."""
		invitation = self.make_invitation()

		invitation.accept()

		self.assertIsNone(invitation.key)
		self.assertFalse(frappe.db.get_value("CRM Invitation", invitation.name, "key"))

	def test_accept_already_accepted_raises(self):
		"""An already-accepted invitation cannot be accepted again."""
		invitation = self.make_invitation()
		invitation.accept()

		invitation.reload()
		with self.assertRaises(frappe.ValidationError):
			invitation.accept()

	def test_accept_expired_invitation_raises(self):
		invitation = self.make_invitation()
		invitation.status = "Expired"
		invitation.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			invitation.accept()

	def test_expire_invitations_survives_one_row_that_will_not_save(self):
		"""One bad row is logged and skipped; the others still expire."""
		from crm.fcrm.doctype.crm_invitation.crm_invitation import CRMInvitation, expire_invitations

		stale = add_days(now(), -4)
		bad = self.make_invitation(email="bad-invitee@example.com")
		good = self.make_invitation(email="good-invitee@example.com")
		for name in (bad.name, good.name):
			frappe.db.set_value("CRM Invitation", name, "creation", stale, update_modified=False)

		real_save = CRMInvitation.save

		def save(doc, *args, **kwargs):
			if doc.name == bad.name:
				raise frappe.ValidationError("cannot save this one")
			return real_save(doc, *args, **kwargs)

		with patch.object(CRMInvitation, "save", save), patch.object(frappe, "log_error") as log_error:
			expire_invitations()

		self.assertEqual(frappe.db.get_value("CRM Invitation", good.name, "status"), "Expired")
		self.assertEqual(frappe.db.get_value("CRM Invitation", bad.name, "status"), "Pending")
		log_error.assert_called_once()

	def test_accept_reports_newly_created_user(self):
		invitation = self.make_invitation(email="brand-new@example.com")

		self.assertTrue(invitation.accept())
		self.assertEqual(frappe.db.get_value("User", invitation.email, "default_app"), "crm")

	def test_accept_reports_existing_user(self):
		frappe.get_doc(
			doctype="User",
			user_type="System User",
			email="already-there@example.com",
			send_welcome_email=0,
			first_name="Already There",
		).insert(ignore_permissions=True)
		invitation = self.make_invitation(email="already-there@example.com")

		self.assertFalse(invitation.accept())

	def test_accept_invitation_sends_new_user_to_set_password(self):
		"""A new user must set a password instead of being logged in directly."""
		from crm.api import accept_invitation

		invitation = self.make_invitation(email="new-invitee@example.com")

		accept_invitation(key=invitation._raw_key)

		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertIn("/update-password?key=", frappe.local.response["location"])

	def test_accept_invitation_logs_in_existing_user(self):
		"""An existing user already has a password, so log them straight in."""
		from crm.api import accept_invitation

		frappe.get_doc(
			doctype="User",
			user_type="System User",
			email="existing-invitee@example.com",
			send_welcome_email=0,
			first_name="Existing Invitee",
		).insert(ignore_permissions=True)
		invitation = self.make_invitation(email="existing-invitee@example.com")

		with patch.object(frappe.local, "login_manager", create=True) as login_manager:
			accept_invitation(key=invitation._raw_key)

		login_manager.login_as.assert_called_once_with("existing-invitee@example.com")
		self.assertEqual(frappe.local.response["location"], "/crm")

	def test_desk_accept_mails_new_user_a_set_password_link(self):
		invitation = self.make_invitation(email="desk-invitee@example.com")

		with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user") as welcome_mail:
			invitation.accept_invitation()

		welcome_mail.assert_called_once()

	def test_desk_accept_does_not_mail_existing_user(self):
		frappe.get_doc(
			doctype="User",
			user_type="System User",
			email="desk-existing@example.com",
			send_welcome_email=0,
			first_name="Desk Existing",
		).insert(ignore_permissions=True)
		invitation = self.make_invitation(email="desk-existing@example.com")

		with patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user") as welcome_mail:
			invitation.accept_invitation()

		welcome_mail.assert_not_called()

	def test_expire_invitations_expires_old_pending_invites(self):
		from crm.fcrm.doctype.crm_invitation.crm_invitation import expire_invitations

		invitation = self.make_invitation(email="stale@example.com")
		frappe.db.set_value(
			"CRM Invitation", invitation.name, "creation", add_days(now(), -4), update_modified=False
		)

		expire_invitations()

		self.assertEqual(frappe.db.get_value("CRM Invitation", invitation.name, "status"), "Expired")

	def test_accept_grants_role_to_user(self):
		invitation = self.make_invitation(email="manager@example.com", role="Sales Manager")

		invitation.accept()

		user = frappe.get_doc("User", invitation.email)
		user_roles = {r.role for r in user.roles}
		self.assertIn("Sales Manager", user_roles)
		self.assertIn("Sales User", user_roles)

	def test_a_dead_key_gets_a_plain_page_not_an_exception(self):
		"""A cancelled or mistyped link used to surface as 'Server Error 417:
		Uncaught Exception' -- frappe's generic page for a guest GET that throws.
		The person holding the link cannot act on that; they can act on a
		sentence telling them to ask for a new invitation."""
		from crm.api import accept_invitation

		accept_invitation(key="no-such-key")

		self.assertEqual(frappe.local.response["type"], "page")
		self.assertEqual(frappe.local.response["http_status_code"], 410)
		self.assertIn("no longer valid", frappe.local.message_title)
		self.assertIn("new invitation", frappe.local.message)

	def test_an_already_accepted_key_gets_the_same_page(self):
		from crm.api import accept_invitation

		invitation = self.make_invitation(email="twice@example.com")
		key = invitation._raw_key
		invitation.accept()

		accept_invitation(key=key)

		self.assertEqual(frappe.local.response["type"], "page")
		self.assertEqual(frappe.local.response["http_status_code"], 410)


MANAGER = "invitation-manager@crmtest.test"
OTHER_MANAGER = "invitation-other-manager@crmtest.test"
REP = "invitation-rep@crmtest.test"


def ensure_user(email: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(*roles)


class InvitationPermissionTest(FrappeTestCase):
	"""The key is a credential; who can read, mint and redeem it is the whole point."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(MANAGER, "Sales Manager", "Sales User")
		ensure_user(OTHER_MANAGER, "Sales Manager", "Sales User")
		ensure_user(REP, "Sales User")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def invite(self, email, role="Sales User", **kwargs):
		with patch.object(frappe, "sendmail") as sendmail:
			doc = frappe.get_doc(doctype="CRM Invitation", email=email, role=role).insert(**kwargs)
		return doc, sendmail

	def test_the_stored_key_is_a_hash_and_only_the_link_carries_the_raw_key(self):
		from crm.fcrm.doctype.crm_invitation.crm_invitation import KEY_LENGTH, hash_key

		invitation, sendmail = self.invite("hashed-invitee@example.com", ignore_permissions=True)
		link = sendmail.call_args.kwargs["args"]["invite_link"]
		raw_key = link.rsplit("key=", 1)[1]

		self.assertEqual(len(raw_key), KEY_LENGTH)
		self.assertNotEqual(raw_key, invitation.key)
		self.assertEqual(hash_key(raw_key), invitation.key)
		self.assertEqual(frappe.db.get_value("CRM Invitation", invitation.name, "key"), hash_key(raw_key))

	def test_the_guest_endpoint_redeems_the_raw_key_against_the_hash(self):
		from crm.api import accept_invitation

		invitation, sendmail = self.invite("redeem-invitee@example.com", ignore_permissions=True)
		raw_key = sendmail.call_args.kwargs["args"]["invite_link"].rsplit("key=", 1)[1]

		frappe.set_user("Guest")
		with patch.object(frappe, "sendmail"):
			accept_invitation(raw_key)
		frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("CRM Invitation", invitation.name, "status"), "Accepted")
		self.assertTrue(frappe.db.exists("User", "redeem-invitee@example.com"))

	def test_a_rep_cannot_list_or_read_invitations(self):
		invitation, _ = self.invite("rep-cannot-see@example.com", ignore_permissions=True)

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("CRM Invitation", fields=["name", "email"])
		self.assertFalse(frappe.has_permission("CRM Invitation", "read", invitation.name))

	def test_a_manager_sees_only_the_invitations_they_sent(self):
		frappe.set_user(MANAGER)
		mine, _ = self.invite("managers-invitee@example.com", ignore_permissions=True)
		frappe.set_user(OTHER_MANAGER)
		theirs, _ = self.invite("other-managers-invitee@example.com", ignore_permissions=True)

		frappe.set_user(MANAGER)
		visible = frappe.get_list("CRM Invitation", pluck="name")
		self.assertIn(mine.name, visible)
		self.assertNotIn(theirs.name, visible)
		self.assertFalse(frappe.has_permission("CRM Invitation", "read", theirs.name))
		# and the key stays out of reach even on their own row: permlevel 1 is admin-only,
		# so the document the client API hands back carries no key
		from frappe.client import get as client_get

		self.assertFalse(client_get("CRM Invitation", mine.name).get("key"))

	def test_a_manager_cannot_insert_an_elevated_invitation_through_either_door(self):
		frappe.set_user(MANAGER)
		# the doctype door: no create grant for Sales Manager
		with self.assertRaises(frappe.PermissionError):
			self.invite("door-one@example.com", role="Sales User")
		# the controller door: ignore_permissions reaches before_insert, which checks the role
		for role in ("Sales Manager", "System Manager"):
			with self.assertRaises(frappe.PermissionError):
				self.invite(
					f"door-two-{role.lower().replace(' ', '-')}@example.com",
					role=role,
					ignore_permissions=True,
				)

	def test_accepting_on_behalf_of_the_invitee_is_for_system_managers_only(self):
		invitation, _ = self.invite("on-behalf@example.com", ignore_permissions=True)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			invitation.accept_invitation()


class ReInviteTest(FrappeTestCase):
	"""An invitation nobody clicked must not lock the address out for good.

	``existing_invites`` matched on email and role with no status, so once a row
	had expired every later invite for that address was silently filtered out and
	no email was ever sent again -- while the page reported success.
	"""

	EMAIL = "reinvite@example.com"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Invitation", {"email": self.EMAIL})
		self.addCleanup(frappe.db.delete, "CRM Invitation", {"email": self.EMAIL})
		# One test in this class signs the address up for real, and creating a
		# User commits -- so without this the invite in every later test finds
		# an existing member and quietly creates nothing.
		self.drop_account()
		self.addCleanup(self.drop_account)

	def drop_account(self):
		if frappe.db.exists("User", self.EMAIL):
			frappe.delete_doc("User", self.EMAIL, force=True, ignore_permissions=True)
			# Deliberate: creating a User commits, so the row this removes outlived
			# the transaction that made it. The delete has to outlive rollback the
			# same way, or the account survives into the next test and the invite
			# there finds an existing member and quietly creates nothing -- exactly
			# the failure setUp's comment describes.
			frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def invite(self):
		from crm.api import invite_by_email

		with patch.object(frappe, "sendmail") as sendmail:
			result = invite_by_email(self.EMAIL, "Sales User")
		return result, sendmail

	def expire_the_invitation(self, name: str):
		from crm.fcrm.doctype.crm_invitation.crm_invitation import expire_invitations

		frappe.db.set_value("CRM Invitation", name, "creation", add_days(now(), -4), update_modified=False)
		expire_invitations()
		self.assertEqual(frappe.db.get_value("CRM Invitation", name, "status"), "Expired")

	def test_a_live_invitation_is_reported_rather_than_sent_twice(self):
		self.invite()
		result, sendmail = self.invite()

		sendmail.assert_not_called()
		self.assertEqual(result["existing_invites"], [self.EMAIL])
		self.assertEqual(result["to_invite"], [])

	def test_an_expired_invitation_can_be_sent_again(self):
		self.invite()
		name = frappe.db.get_value("CRM Invitation", {"email": self.EMAIL})
		self.expire_the_invitation(name)

		result, sendmail = self.invite()

		sendmail.assert_called_once()
		self.assertEqual(result["to_invite"], [self.EMAIL])
		self.assertEqual(result["existing_invites"], [])
		# the dead row is gone rather than reopened: expiry counts from `creation`,
		# so a revived row would go straight back to Expired on the next nightly run
		self.assertFalse(frappe.db.exists("CRM Invitation", name))
		rows = frappe.get_all("CRM Invitation", filters={"email": self.EMAIL}, pluck="status")
		self.assertEqual(rows, ["Pending"])

	def test_an_address_that_already_has_an_account_is_reported_not_invited(self):
		frappe.get_doc(
			doctype="User",
			user_type="System User",
			email=self.EMAIL,
			send_welcome_email=0,
			first_name="Already A Member",
		).insert(ignore_permissions=True)

		result, sendmail = self.invite()

		sendmail.assert_not_called()
		self.assertEqual(result["existing_members"], [self.EMAIL])
		self.assertEqual(result["to_invite"], [])
