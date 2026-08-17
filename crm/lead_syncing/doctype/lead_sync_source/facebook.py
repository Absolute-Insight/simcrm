from urllib.parse import urlparse

import frappe
from frappe.exceptions import ValidationError
from frappe.integrations.utils import make_get_request

FB_GRAPH_API_BASE = "https://graph.facebook.com"
FB_GRAPH_API_VERSION = "v23.0"

# Graph caps a leads page well below anything we would ask for, so the page size
# is a request, never a guarantee -- which is the whole reason the cursor has to
# be followed rather than assumed away.
LEADS_PAGE_SIZE = 100

# A backstop, not an expected limit. At 100 a page this is 50,000 leads in one
# run; a cursor that keeps answering past that is a loop, not a busy campaign,
# and a scheduled job must not spin on it forever.
MAX_LEAD_PAGES = 500

# The paging cursor is a URL out of a response body, and it carries the page
# access token. Following one that points somewhere else would hand that token
# to whoever supplied it, so the host is checked before every hop.
ALLOWED_GRAPH_HOSTS = ("graph.facebook.com",)


class DuplicateLeadError(ValidationError):
	pass


def get_fb_graph_api_url(endpoint: str) -> str:
	if endpoint.startswith("/"):
		endpoint = endpoint[1:]

	return f"{FB_GRAPH_API_BASE}/{FB_GRAPH_API_VERSION}/{endpoint}"


class FacebookSyncSource:
	def __init__(
		self,
		access_token: str,
		form_id: str,
		source_name: str | None = None,
	):
		self.access_token = access_token
		self.form_id = form_id
		self.source_name = source_name
		self.form_questions_mapping = None

	def get_api_url(self, endpoint: str) -> str:
		return get_fb_graph_api_url(endpoint)

	def sync(self):
		"""Import every new lead, then move the watermark to the newest one handled.

		The watermark used to be set to ``now()`` regardless of what came back.
		Combined with a single unpaginated fetch that meant a form with more new
		leads than fit one page handed over a partial batch and the rest were
		marked synced without ever being asked for -- gone, with the run
		reporting success. So the two halves are tied together here: the
		watermark only ever advances as far as a lead this run actually dealt
		with, and if the fetch throws partway it advances only over what was
		already handled.
		"""
		handled_through = None
		try:
			for lead in self.fetch_leads():
				self.sync_single_lead(lead)
				# "Handled" covers a lead written to Failed Lead Sync Log as well
				# as one imported: it is recorded either way, so re-asking for it
				# would only produce the same log line again. A lead that raised
				# past sync_single_lead's own catch never gets here.
				handled_through = max(handled_through or "", lead.get("created_time") or "")
		finally:
			self.update_last_synced_at(handled_through)

	def fetch_page(self, url: str, params: dict | None = None) -> dict:
		"""One Graph request, refusing any URL that is not Graph's own."""
		host = (urlparse(url).hostname or "").lower()
		if host not in ALLOWED_GRAPH_HOSTS:
			frappe.throw(frappe._("Refusing to follow a lead-paging URL pointing at {0}").format(host or url))
		return make_get_request(url, params=params) or {}

	def already_imported(self, lead_id: str) -> bool:
		"""This exact Facebook lead is already a CRM Lead.

		Distinct from :meth:`validate_duplicate_lead`, which matches on the
		answers somebody typed -- two people can share a name and an empty
		phone, and a person can genuinely fill the same form twice, so that one
		is worth a log line. Seeing the same lead *id* twice is just the
		one-second overlap the watermark leaves on purpose, and logging it every
		run would bury the real duplicates.
		"""
		return bool(lead_id) and frappe.db.exists("CRM Lead", {"facebook_lead_id": lead_id})

	def sync_single_lead(self, lead, raise_exception=False):
		if self.already_imported(lead.get("id")):
			return None

		question_to_field_map = self.get_form_questions_mapping()
		lead_data = {item["name"]: item["values"][0] for item in lead["field_data"]}
		crm_lead_data = {
			question_to_field_map.get(k): v for k, v in lead_data.items() if k in question_to_field_map
		}
		crm_lead_data["source"] = "Facebook"
		crm_lead_data["facebook_lead_id"] = lead["id"]
		crm_lead_data["facebook_form_id"] = self.form_id

		try:
			self.validate_duplicate_lead(crm_lead_data, question_to_field_map)
			return frappe.get_doc(
				{
					"doctype": "CRM Lead",
					**crm_lead_data,
				}
			).insert(ignore_permissions=True)
		except (frappe.UniqueValidationError, DuplicateLeadError):
			self.create_failure_log(lead, "Duplicate")
			if raise_exception:
				raise
		except Exception:
			self.create_failure_log(lead, traceback=frappe.get_traceback(with_context=True))
			if raise_exception:
				raise

	def fetch_leads(self):
		"""Yield every new lead, following Graph's paging cursor to the end.

		A generator on purpose: ``sync`` advances its watermark per lead, so a
		failure on page four still leaves pages one to three imported and the
		watermark sitting exactly where the import got to. Materialising the
		whole set first would throw all of that away on the last page's error.
		"""
		url = self.get_api_url(f"/{self.form_id}/leads")
		params = {
			"access_token": self.access_token,
			"fields": "id,created_time,field_data",
			"limit": LEADS_PAGE_SIZE,
		}

		if self.last_synced_at:
			timestamp = frappe.utils.data.get_timestamp(self.last_synced_at)
			params["filtering"] = frappe.as_json(
				[{"field": "time_created", "operator": "GREATER_THAN", "value": timestamp}]
			)

		for _page in range(MAX_LEAD_PAGES):
			response = self.fetch_page(url, params=params)
			yield from response.get("data") or []

			# The cursor already carries the token, the fields and the filter, so
			# the follow-up request must not re-add them.
			url = (response.get("paging") or {}).get("next")
			params = None
			if not url:
				return

		frappe.log_error(
			title="Facebook lead sync: paging did not terminate",
			message=(
				f"Stopped after {MAX_LEAD_PAGES} pages for form {self.form_id}. Leads beyond"
				" that point were not imported; the watermark has not moved past them, so the"
				" next run resumes from the same place."
			),
		)

	def get_form_questions_mapping(self):
		if self.form_questions_mapping:
			return self.form_questions_mapping

		form_questions = frappe.db.get_all(
			"Facebook Lead Form Question",
			filters={"parent": self.form_id},
			fields=["key", "mapped_to_crm_field"],
		)
		self.form_questions_mapping = {
			q["key"]: q["mapped_to_crm_field"] for q in form_questions if q["mapped_to_crm_field"]
		}

		return self.form_questions_mapping

	@property
	def last_synced_at(self):
		return frappe.db.get_value(
			"Lead Sync Source", self.source_name or {"facebook_lead_form": self.form_id}, "last_synced_at"
		)

	def create_failure_log(
		self, lead_data: dict | None = None, type: str = "Failure", traceback: str | None = None
	):
		return frappe.get_doc(
			{
				"doctype": "Failed Lead Sync Log",
				"type": type,
				"lead_data": frappe.as_json(lead_data),
				"source": self.get_source_name(),
				"traceback": traceback,
			}
		).insert(ignore_permissions=True)

	def update_last_synced_at(self, handled_through: str | None = None):
		"""Move the watermark to the newest lead handled -- never to ``now()``.

		``now()`` was the bug: it claimed everything up to this instant had been
		imported when only the first page had, and the next run's
		``time_created > watermark`` filter then never asked for the rest.

		Nothing handled means nothing moves. A run that fetched no leads, or
		failed before its first one, must leave the watermark where it is.

		The mark is set one second *behind* the newest lead. Graph's
		``time_created`` is second-granular and the filter is strictly greater,
		so a lead created in the same second as the last one seen -- but reaching
		Facebook after this request -- would otherwise never be asked for. The
		cost is re-fetching one second of leads next run, and
		:meth:`already_imported` drops those without a word.
		"""
		if not handled_through:
			return

		newest = frappe.utils.get_datetime(handled_through)
		frappe.db.set_value(
			"Lead Sync Source",
			self.source_name or {"facebook_lead_form": self.form_id},
			"last_synced_at",
			frappe.utils.add_to_date(newest, seconds=-1),
		)

	def get_source_name(self):
		if self.source_name:
			return self.source_name

		return frappe.db.get_value("Lead Sync Source", {"facebook_lead_form": self.form_id}, "name")

	def validate_duplicate_lead(self, lead_data: dict, field_mapping: dict):
		validation_filters = {crm_field: lead_data[crm_field] for crm_field in field_mapping.values()}
		validation_filters["facebook_form_id"] = lead_data["facebook_form_id"]  # only for this campaign
		if frappe.db.exists("CRM Lead", validation_filters):
			raise DuplicateLeadError


@frappe.whitelist()
def fetch_and_store_pages_from_facebook(access_token: str) -> list[dict]:
	if not access_token:
		frappe.throw(frappe._("Access token is required"))

	account_details = get_fb_account_details(access_token)
	if not account_details.get("id"):
		frappe.throw(frappe._("Invalid access token provided for Facebook."))

	url = get_fb_graph_api_url("/me/accounts")
	pages = make_get_request(url, params={"access_token": access_token}).get("data", [])
	for page in pages:
		page_id = page["id"]
		already_synced = frappe.db.exists("Facebook Page", page_id)
		if not already_synced:
			create_facebook_page_in_db(page, account_details)
		forms = fetch_and_store_leadgen_forms_from_facebook(page_id, page["access_token"])
		page["forms"] = forms

	return pages


def get_fb_account_details(access_token: str) -> dict:
	url = get_fb_graph_api_url("me")
	try:
		response = make_get_request(url, params={"access_token": access_token})
	except Exception as _:
		frappe.throw(frappe._("Please check your access token"))
	return response


def create_facebook_page_in_db(page: dict, account_details: dict) -> None:
	frappe.get_doc(
		{
			"doctype": "Facebook Page",
			"page_name": page["name"],
			"id": page["id"],
			"category": page["category"],
			"access_token": page["access_token"],
			"account_id": account_details["id"],
		}
	).insert(ignore_permissions=True)


def fetch_and_store_leadgen_forms_from_facebook(page_id: str, page_access_token: str) -> list[dict]:
	fields = "id,name,questions"
	url = get_fb_graph_api_url(f"/{page_id}/leadgen_forms")
	forms = make_get_request(
		url,
		params={
			"access_token": page_access_token,
			"fields": fields,
			"limit": 15000,
		},
	).get("data", [])
	for form in forms:
		form_id = form["id"]
		already_synced = frappe.db.exists("Facebook Lead Form", form_id)
		if already_synced:
			continue
		create_facebook_lead_form_in_db(form, page_id)

	return forms


def create_facebook_lead_form_in_db(form: dict, page_id: str) -> None:
	form_doc = frappe.get_doc(
		{
			"doctype": "Facebook Lead Form",
			"form_name": form["name"],
			"id": form["id"],
			"page": page_id,
			"questions": form["questions"],
		}
	)
	form_doc.insert(ignore_permissions=True)


@frappe.whitelist()
def get_pages_with_forms() -> list[dict]:
	pages = frappe.db.get_all("Facebook Page", fields=["id", "name"])
	for page in pages:
		forms = frappe.db.get_all("Facebook Lead Form", filters={"page": page["id"]}, fields=["id", "name"])
		page["forms"] = forms
	return pages
