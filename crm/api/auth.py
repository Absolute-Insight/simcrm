import frappe


# Guest access is required -- the login screen has to know which "Sign in with..."
# buttons to draw before anyone is signed in. The client secret is decrypted only
# to skip half-configured providers; it is never part of the response, which
# carries the provider name, the public authorize URL and an icon.
@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def oauth_providers():
	from frappe.utils.html_utils import get_icon_html
	from frappe.utils.oauth import get_oauth2_authorize_url, get_oauth_keys
	from frappe.utils.password import get_decrypted_password

	out = []
	providers = frappe.get_all(
		"Social Login Key",
		filters={"enable_social_login": 1},
		fields=["name", "client_id", "base_url", "provider_name", "icon"],
		order_by="name",
	)

	for provider in providers:
		client_secret = get_decrypted_password("Social Login Key", provider.name, "client_secret")
		if not client_secret:
			continue

		icon = None
		if provider.icon:
			if provider.provider_name == "Custom":
				icon = get_icon_html(provider.icon, small=True)
			else:
				icon = f"<img src='{provider.icon}' alt={provider.provider_name}>"

		if provider.client_id and provider.base_url and get_oauth_keys(provider.name):
			out.append(
				{
					"name": provider.name,
					"provider_name": provider.provider_name,
					"auth_url": get_oauth2_authorize_url(provider.name, "/crm"),
					"icon": icon,
				}
			)
	return out


CRM_ONLY_ROLES = ("Sales User", "Sales Manager")


def land_in_crm(login_manager):
	"""Send someone whose job is the CRM to the CRM when they sign in.

	frappe answers a form login with ``get_home_page()``, which for any internal
	user with no role home page is the desk. A rep who typed their password
	landed on an apps screen holding a single icon, and had to know to click
	it. Only a link that carried ``redirect-to``, or the set-password link in an
	invitation, went to the CRM.

	``flags.home_page`` is what ``get_home_page`` reads first and it lasts for
	this request only, so nothing else that asks for the home page (the site
	root, the portal) changes its answer. A System Manager keeps the desk: it is
	where they administer the site from.
	"""
	roles = frappe.get_roles(login_manager.user)
	if "System Manager" in roles or not any(role in roles for role in CRM_ONLY_ROLES):
		return
	frappe.local.flags.home_page = "crm"


def name_field_user(login_manager=None):
	"""Name the signed-in user in a cookie that outlives the browser session.

	The cached shell that opens the app with no network has to know whose saved
	copy to show, and ``user_id`` cannot tell it: frappe sets that as a session
	cookie, and a phone drops those when it closes the app. This one lasts as
	long as a pack does.

	Set on every ``/crm`` render and on **every new session**, wherever it lands
	(``on_session_creation``: after frappe has accepted the login, not before). The
	login matters on a shared device: someone who signs in and goes to the desk
	never renders ``/crm``, and without this the cookie would go on naming the
	last rep -- whose saved customers the shell would then open for the new
	user. With it, the cookie names the new user, the device's stores are still
	the old one's, and the shell opens for neither.

	It authenticates nothing -- the server never reads it. It is readable by
	script, like ``user_id``, because the shell's loader is script.
	"""
	from crm.api.offline import FIELD_USER_COOKIE, PACK_MAX_AGE_DAYS

	cookies = getattr(frappe.local, "cookie_manager", None)
	user = getattr(login_manager, "user", None) or frappe.session.user
	if cookies and user and user != "Guest":
		cookies.set_cookie(FIELD_USER_COOKIE, user, max_age=PACK_MAX_AGE_DAYS * 86400)


def forget_field_user(login_manager=None):
	"""Logout, from anywhere: the cached shell must stop opening for this user.

	The app's own logout also empties the device's stores, but a logout from the
	desk runs none of the app's code -- this hook is the part that still runs.

	frappe fires ``on_logout`` before it looks at whose session is ending, so an
	administrator signing *someone else* out loses their own cookie here too.
	That is the safe direction, and the next ``/crm`` render puts it back.
	"""
	from crm.api.offline import FIELD_USER_COOKIE

	# no cookie jar outside a request (a session cleared from a job or the console)
	cookies = getattr(frappe.local, "cookie_manager", None)
	if cookies:
		cookies.delete_cookie(FIELD_USER_COOKIE)
