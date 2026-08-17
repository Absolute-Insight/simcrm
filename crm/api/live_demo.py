# Copyright (c) 2024, Frappe Technologies and contributors
# This file is used to handle live demo site (https://frappecrm-demo.frappe.cloud) related API calls and hooks

import frappe
from frappe import _
from frappe.auth import LoginManager


# Guest access is required, and this endpoint really does sign the caller in
# without a password -- that is the whole point of the public demo site it was
# written for. It returns immediately unless BOTH demo_username and
# demo_password are set in site config, so it is inert on a normal site.
#
# Setting those two keys on a production site is an authentication bypass by
# design: anyone who can reach /api/method/crm.api.live_demo.login becomes the
# demo user. Do not set them outside a throwaway demo site.
@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def login():
	if not frappe.conf.demo_username or not frappe.conf.demo_password:
		return
	frappe.local.response["redirect_to"] = "/crm"
	login_manager = LoginManager()
	login_manager.authenticate(frappe.conf.demo_username, frappe.conf.demo_password)
	login_manager.post_login()
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = frappe.local.response["redirect_to"]


def validate_reset_password(doc, event):
	if frappe.conf.demo_username and frappe.session.user == frappe.conf.demo_username:
		frappe.throw(
			_("Password cannot be reset by Demo User {}").format(frappe.bold(frappe.conf.demo_username)),
			frappe.PermissionError,
		)


def validate_user(doc, event):
	if frappe.conf.demo_username and frappe.session.user == frappe.conf.demo_username and doc.new_password:
		frappe.throw(
			_("Password cannot be reset by Demo User {}").format(frappe.bold(frappe.conf.demo_username)),
			frappe.PermissionError,
		)
