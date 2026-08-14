# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


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
			"pipeline_by_stage", "funnel_conversion", "plan_adherence_by_rep", "forecast_vs_actual"
		]
	# end: auto-generated types

	def validate(self):
		for email in self.recipient_list():
			validate_email_address(email, throw=True)

	def recipient_list(self) -> list[str]:
		return [e.strip() for e in (self.recipients or "").split(",") if e.strip()]


def send_due_digests():
	"""Daily scheduler entry. Weekly digests fire on Mondays."""
	from crm.api.reports import REPORTS

	is_monday = frappe.utils.getdate().weekday() == 0
	digests = frappe.get_all(
		"CRM Report Digest",
		filters={"enabled": 1},
		fields=["name", "report", "frequency", "recipients"],
	)

	sent = 0
	for digest in digests:
		if digest.frequency == "Weekly" and not is_monday:
			continue
		report_def = REPORTS.get(digest.report)
		if not report_def:
			continue

		today = frappe.utils.nowdate()
		if digest.frequency == "Weekly":
			from_date = frappe.utils.add_days(today, -7)
		else:
			from_date = frappe.utils.add_days(today, -1)

		rows = report_def["get_rows"](str(from_date), str(today), None)
		recipients = [e.strip() for e in (digest.recipients or "").split(",") if e.strip()]
		if not recipients:
			continue

		frappe.sendmail(
			recipients=recipients,
			subject=_("Vectora digest: {0}").format(report_def["title"]),
			message=_render_digest(report_def, rows, from_date, today),
		)
		sent += 1
	return sent


def _render_digest(report_def, rows, from_date, to_date) -> str:
	columns = report_def["columns"]
	head = "".join(
		f'<th style="text-align:left;padding:6px 12px;border-bottom:2px solid #ebebf3;'
		f'font-size:12px;color:#7a7990;text-transform:uppercase;letter-spacing:0.04em">'
		f"{col['label']}</th>"
		for col in columns
	)
	body = ""
	for row in rows:
		cells = "".join(
			f'<td style="padding:6px 12px;border-bottom:1px solid #f2f2f8;'
			f'font-variant-numeric:tabular-nums">{row.get(col["key"], "")}</td>'
			for col in columns
		)
		body += f"<tr>{cells}</tr>"
	if not rows:
		body = (
			f'<tr><td colspan="{len(columns)}" style="padding:12px;color:#7a7990">'
			+ _("No data in this period.")
			+ "</td></tr>"
		)

	return f"""
	<div style="font-family:ui-sans-serif,system-ui,sans-serif;color:#16161f">
		<h2 style="font-size:18px;margin:0 0 4px">{report_def["title"]}</h2>
		<p style="margin:0 0 16px;color:#7a7990;font-size:13px">
			{from_date} – {to_date}
		</p>
		<table style="border-collapse:collapse;width:100%">
			<thead><tr>{head}</tr></thead>
			<tbody>{body}</tbody>
		</table>
		<p style="margin:16px 0 0;color:#9695ab;font-size:12px">Vectora</p>
	</div>
	"""
