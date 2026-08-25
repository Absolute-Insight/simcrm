import frappe
from frappe import _


@frappe.whitelist()
def create_email_account(data: dict):
	frappe.only_for(["System Manager", "Sales Manager"], True)
	service = data.get("service")
	if service == "Custom":
		service_config = custom_service_config(data)
		if not service_config:
			frappe.throw(_("IMAP server and SMTP server are required for a custom account"))
	else:
		service_config = email_service_config.get(service)
	if not service_config:
		return "Service not supported"

	try:
		email_doc = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_id": data.get("email_id"),
				"email_account_name": data.get("email_account_name"),
				# "Custom" is a UI concept, not an Email Account select option; a
				# custom account is stored with no service, its servers explicit.
				"service": "" if service == "Custom" else service,
				"enable_incoming": data.get("enable_incoming"),
				"enable_outgoing": data.get("enable_outgoing"),
				"default_incoming": data.get("default_incoming"),
				"default_outgoing": data.get("default_outgoing"),
				"email_sync_option": "ALL",
				"initial_sync_count": 100,
				"create_contact": 1,
				"track_email_status": 1,
				"use_tls": 1,
				"use_imap": 1,
				"smtp_port": 587,
				# Lead capture is the Communication hook's job
				# (crm.utils.create_lead_from_incoming_email), gated per account by
				# this custom field. Frappe-core ingestion via append_to must stay
				# unset: it would create a CRM Lead from every incoming email,
				# ignoring this toggle.
				"create_lead_from_incoming_email": 1 if data.get("create_lead_from_incoming_email") else 0,
				**service_config,
			}
		)
		if service == "Frappe Mail":
			email_doc.api_key = data.get("api_key")
			email_doc.api_secret = data.get("api_secret")
			email_doc.frappe_mail_site = data.get("frappe_mail_site")
		else:
			email_doc.append("imap_folder", {"folder_name": "INBOX"})
			email_doc.password = data.get("password")
			# validate whether the credentials are correct
			email_doc.get_incoming_server()

		# if correct credentials, save the email account
		email_doc.save()
	except Exception:
		# The raw exception can carry the mail host's banner and the credentials
		# we just sent; log it for the admin and give the user a generic message.
		frappe.log_error(frappe.get_traceback(), "Email account setup failed")
		frappe.throw(_("Could not connect to the mail server. Check the credentials and try again."))


email_service_config = {
	"Frappe Mail": {
		"domain": None,
		"password": None,
		"awaiting_password": 0,
		"ascii_encode_password": 0,
		"login_id_is_different": 0,
		"login_id": None,
		"use_imap": 0,
		"use_ssl": 0,
		"validate_ssl_certificate": 0,
		"use_starttls": 0,
		"email_server": None,
		"incoming_port": 0,
		"always_use_account_email_id_as_sender": 1,
		"use_tls": 0,
		"use_ssl_for_outgoing": 0,
		"smtp_server": None,
		"smtp_port": None,
		"no_smtp_authentication": 0,
	},
	"GMail": {
		"email_server": "imap.gmail.com",
		"use_ssl": 1,
		"smtp_server": "smtp.gmail.com",
	},
	"Outlook": {
		"email_server": "imap-mail.outlook.com",
		"use_ssl": 1,
		"smtp_server": "smtp-mail.outlook.com",
	},
	"Sendgrid": {
		"smtp_server": "smtp.sendgrid.net",
		"smtp_port": 587,
	},
	"SparkPost": {
		"smtp_server": "smtp.sparkpostmail.com",
	},
	"Yahoo": {
		"email_server": "imap.mail.yahoo.com",
		"use_ssl": 1,
		"smtp_server": "smtp.mail.yahoo.com",
		"smtp_port": 587,
	},
	"Yandex": {
		"email_server": "imap.yandex.com",
		"use_ssl": 1,
		"smtp_server": "smtp.yandex.com",
		"smtp_port": 587,
	},
}


def custom_service_config(data: dict) -> dict | None:
	"""Server settings for the "Custom" (any IMAP/SMTP provider) service.

	Every other service ships a fixed entry in email_service_config; a custom
	provider's servers come from the form instead. Incoming defaults to SSL
	(port 993, STARTTLS when SSL is off), and SMTP port 465 -- implicit-TLS by
	definition -- switches outgoing from STARTTLS to SSL, so the two well-known
	port conventions both work without extra checkboxes.
	"""
	from frappe.utils import cint

	email_server = (data.get("email_server") or "").strip()
	smtp_server = (data.get("smtp_server") or "").strip()
	if not email_server or not smtp_server:
		return None

	use_ssl = cint(data.get("use_ssl", 1))
	smtp_port = cint(data.get("smtp_port")) or 587
	smtp_ssl = 1 if smtp_port == 465 else 0
	return {
		"email_server": email_server,
		"use_ssl": use_ssl,
		"use_starttls": 0 if use_ssl else 1,
		"smtp_server": smtp_server,
		"smtp_port": smtp_port,
		"use_ssl_for_outgoing": smtp_ssl,
		"use_tls": 0 if smtp_ssl else 1,
	}
