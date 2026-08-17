# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, validate_email_address

CRM_ROLES = ("Sales User", "Sales Manager", "System Manager")


class CRMReportDigest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		frequency: DF.Literal["Daily", "Weekly"]
		name: DF.Int | None
		recipients: DF.SmallText
		report: DF.Literal[
			"pipeline_by_stage",
			"funnel_conversion",
			"plan_adherence_by_rep",
			"forecast_vs_actual",
			"quota_attainment_by_rep",
		]
	# end: auto-generated types

	def validate(self):
		self.validate_report()
		for email in self.recipient_list():
			validate_email_address(email, throw=True)
			self.validate_internal_user(email)

	def validate_report(self) -> None:
		"""The Select and the report registry are two lists that must not drift.

		They already had: ``quota_attainment_by_rep`` shipped as a report and was
		never added here, so the one report a sales manager most wants mailed to
		them could not be scheduled at all. The send loop skips an unknown key
		silently -- correct, since a report can be withdrawn while a digest row
		still names it -- which means a mismatch costs a digest that quietly
		never arrives. Refuse it at save instead. ``test_report_digest`` asserts
		the two lists are equal, so the drift cannot reach a site either.
		"""
		from crm.api.reports import REPORTS

		if self.report and self.report not in REPORTS:
			frappe.throw(_("{0} is not a report this site publishes.").format(self.report))

	def validate_internal_user(self, email: str) -> None:
		"""A digest carries deal values, so it may only go to someone who could
		already read them in the app — never to an arbitrary outside address."""
		if not frappe.db.exists("User", {"name": email, "enabled": 1}):
			frappe.throw(_("{0} is not an enabled user of this site.").format(email))
		if not set(frappe.get_roles(email)) & set(CRM_ROLES):
			frappe.throw(_("{0} has no CRM role, so they cannot receive CRM data.").format(email))

	def recipient_list(self) -> list[str]:
		return [e.strip() for e in (self.recipients or "").split(",") if e.strip()]


def _still_entitled(email: str) -> bool:
	"""The save-time rule from ``validate_internal_user``, asked again at send.

	Same two conditions -- an enabled user of this site, holding a CRM role --
	expressed as a predicate because the send loop must skip a recipient rather
	than throw and take the whole digest down with it.
	"""
	if not frappe.db.exists("User", {"name": email, "enabled": 1}):
		return False
	return bool(set(frappe.get_roles(email)) & set(CRM_ROLES))


def send_due_digests():
	"""Daily scheduler entry. Weekly digests fire on Mondays."""
	from crm.api.reports import REPORTS, get_report

	is_monday = frappe.utils.getdate().weekday() == 0
	digests = frappe.get_all(
		"CRM Report Digest",
		filters={"enabled": 1},
		fields=["name", "report", "frequency", "recipients"],
	)

	sent = 0
	for digest in digests:
		# one bad digest must not take the rest of the day's mail down with it,
		# the same isolation crm/automation.py gives each rule
		try:
			if digest.frequency == "Weekly" and not is_monday:
				continue
			report_def = REPORTS.get(digest.report)
			if not report_def:
				continue

			today = frappe.utils.nowdate()
			days = 7 if digest.frequency == "Weekly" else 1
			from_date = frappe.utils.add_days(today, -days)

			recipients = [e.strip() for e in (digest.recipients or "").split(",") if e.strip()]
			# Re-check at send time, not just at save time. validate() runs when
			# somebody edits the digest; offboarding happens somewhere else
			# entirely, so a rep who has been disabled and stripped of their
			# roles kept receiving pipeline values at a personal address every
			# day, indefinitely, and the deploy runbook told operators these
			# were validated. Dropping a recipient is silent on purpose -- the
			# digest still goes to everyone still entitled to it.
			recipients = [email for email in recipients if _still_entitled(email)]
			if not recipients:
				continue

			for recipient in recipients:
				# rendered as the recipient, not as the scheduler: a rep gets
				# their own rows and a manager gets the team's, exactly as each
				# would see on the Reports page
				original_user = frappe.session.user
				try:
					# Deliberate: this is what scopes the digest to its recipient, and the
					# finally below restores the scheduler user unconditionally.
					# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser
					frappe.set_user(recipient)
					report = get_report(digest.report, str(from_date), str(today))
				finally:
					# nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser
					frappe.set_user(original_user)

				frappe.sendmail(
					recipients=[recipient],
					subject=_("Vectora digest: {0}").format(report["title"]),
					message=_render_digest(report, from_date, today),
					reference_doctype="CRM Report Digest",
					reference_name=digest.name,
				)
			sent += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"CRM Report Digest {digest.name} failed")
			continue
	return sent


# Email clients ignore stylesheets, so every rule has to be inline. Naming the
# two of them keeps the markup on one line each and readable, instead of a run of
# implicitly concatenated string literals that reads like a list missing a comma.
TH_STYLE = (
	"text-align:left;padding:6px 12px;border-bottom:2px solid #ebebf3;"
	"font-size:12px;color:#7a7990;text-transform:uppercase;letter-spacing:0.04em"
)
TD_STYLE = "padding:6px 12px;border-bottom:1px solid #f2f2f8;font-variant-numeric:tabular-nums"


def _render_digest(report, from_date, to_date) -> str:
	"""Every interpolation is escaped: report cells carry user-authored text —
	stage names, lost reasons, user names — straight into an email body."""
	columns = report["columns"]
	head = "".join(f'<th style="{TH_STYLE}">{escape_html(str(col["label"]))}</th>' for col in columns)
	body = ""
	for row in report["rows"]:
		cells = "".join(
			f'<td style="{TD_STYLE}">{escape_html(str(row.get(col["key"], "")))}</td>' for col in columns
		)
		body += f"<tr>{cells}</tr>"
	if not report["rows"]:
		body = (
			f'<tr><td colspan="{len(columns)}" style="padding:12px;color:#7a7990">'
			+ _("No data in this period.")
			+ "</td></tr>"
		)

	return f"""
	<div style="font-family:ui-sans-serif,system-ui,sans-serif;color:#16161f">
		<h2 style="font-size:18px;margin:0 0 4px">{escape_html(str(report["title"]))}</h2>
		<p style="margin:0 0 16px;color:#7a7990;font-size:13px">
			{escape_html(str(from_date))} – {escape_html(str(to_date))}
		</p>
		<table style="border-collapse:collapse;width:100%">
			<thead><tr>{head}</tr></thead>
			<tbody>{body}</tbody>
		</table>
		<p style="margin:16px 0 0;color:#9695ab;font-size:12px">Vectora</p>
	</div>
	"""
