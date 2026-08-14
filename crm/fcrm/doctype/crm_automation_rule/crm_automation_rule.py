# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMAutomationRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["Create Task", "Create Suggestion"]
		assign_to_owner: DF.Check
		condition: DF.Code | None
		description_template: DF.SmallText | None
		document_type: DF.Link
		due_in_days: DF.Int
		enabled: DF.Check
		task_priority: DF.Literal["Low", "Medium", "High"]
		title: DF.Data
		title_template: DF.Data
		to_status: DF.Data | None
		trigger: DF.Literal["Created", "Status Changed"]
	# end: auto-generated types

	SUPPORTED_DOCTYPES = ("CRM Lead", "CRM Deal")

	def validate(self):
		if self.document_type not in self.SUPPORTED_DOCTYPES:
			frappe.throw(_("Automation rules support {0} only.").format(", ".join(self.SUPPORTED_DOCTYPES)))
		if self.condition:
			# surface syntax errors at save time, not at run time
			try:
				frappe.safe_eval(self.condition, eval_locals={"doc": frappe._dict()})
			except (SyntaxError, NameError) as e:
				frappe.throw(_("Invalid condition: {0}").format(e))
			except Exception:
				# evaluation errors against the empty doc are fine; syntax is what we check
				pass
