# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""A page's access token is a secret at rest.

It was a Small Text: in ``tabFacebook Page`` in the clear, in every backup, and
returned by ``/api/resource/Facebook Page`` to anyone who could read the doctype.
These pin the Password field, and the patch that moves the tokens an existing
site already holds into the encrypted store without losing one.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import get_decrypted_password

from crm.lead_syncing.doctype.lead_sync_source.facebook import create_facebook_page_in_db
from crm.patches.v1_0.encrypt_facebook_page_access_token import execute as encrypt_tokens

TOKEN = "EAAG-page-token-" + "x9" * 90  # as long as a real one: well past 140 characters


class IntegrationTestFacebookPage(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _page(self, page_id, token=TOKEN):
		create_facebook_page_in_db(
			{"name": f"Page {page_id}", "id": page_id, "category": "Shop", "access_token": token},
			{"id": "acct-1"},
		)
		return page_id

	def _column(self, name):
		return frappe.db.get_value("Facebook Page", name, "access_token")

	def _as_before_the_upgrade(self, name, token):
		"""The row an existing site holds: the token in the column, nothing in __Auth."""
		frappe.db.set_value("Facebook Page", name, "access_token", token, update_modified=False)
		frappe.db.delete("__Auth", {"doctype": "Facebook Page", "name": name, "fieldname": "access_token"})

	def _stored(self, name):
		return get_decrypted_password("Facebook Page", name, "access_token", raise_exception=False)

	def test_the_field_is_a_password(self):
		self.assertEqual(frappe.get_meta("Facebook Page").get_field("access_token").fieldtype, "Password")

	def test_a_connected_page_keeps_its_token_out_of_the_table(self):
		name = self._page("fbp-new")

		self.assertEqual(set(self._column(name)), {"*"})
		rows = frappe.get_all("Facebook Page", filters={"name": name}, fields=["access_token"])
		self.assertNotIn(TOKEN, str(rows))
		# and it is still the page's token for whoever is meant to use it
		self.assertEqual(frappe.get_doc("Facebook Page", name).get_password("access_token"), TOKEN)

	def test_the_patch_moves_an_existing_token_into_the_encrypted_store(self):
		name = self._page("fbp-old")
		self._as_before_the_upgrade(name, TOKEN)
		self.assertEqual(self._column(name), TOKEN)
		self.assertIsNone(self._stored(name))
		modified = frappe.db.get_value("Facebook Page", name, "modified")

		encrypt_tokens()

		self.assertEqual(self._column(name), "*" * len(TOKEN))
		self.assertEqual(self._stored(name), TOKEN)
		self.assertEqual(frappe.get_doc("Facebook Page", name).get_password("access_token"), TOKEN)
		# a data fix, not an edit: no Version row to carry the token, no new timestamp
		self.assertEqual(frappe.db.get_value("Facebook Page", name, "modified"), modified)
		self.assertFalse(frappe.db.exists("Version", {"ref_doctype": "Facebook Page", "docname": name}))

	def test_the_patch_can_run_again_without_losing_a_token(self):
		old = self._page("fbp-rerun-old")
		self._as_before_the_upgrade(old, TOKEN)
		encrypt_tokens()
		# connected after the upgrade, with a token of its own
		new = self._page("fbp-rerun-new", token="EAAG-second-token")

		encrypt_tokens()
		encrypt_tokens()

		self.assertEqual(self._stored(old), TOKEN)
		self.assertEqual(self._stored(new), "EAAG-second-token")
		self.assertEqual(set(self._column(old)), {"*"})

	def test_a_page_without_a_token_is_left_alone(self):
		name = self._page("fbp-empty")
		self._as_before_the_upgrade(name, "")

		encrypt_tokens()

		self.assertFalse(self._column(name))
		self.assertIsNone(self._stored(name))
