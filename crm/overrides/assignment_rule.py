"""Mixed into the Assignment Rule controller by extend_doctype_class (see hooks.py).

Marks the assignment a rule is making while it makes it, so that
``crm.api.todo.may_assign`` can tell a rule's own ToDo from one a client wrote
with ``assignment_rule`` filled in. That field is an ordinary column: the form
marks it read-only, but ``frappe.client.insert`` and the whitelisted
``assign_to.add`` both copy it from the request.
"""

import frappe


class AssignmentRuleRun:
	def do_assignment(self, doc):
		previous = frappe.flags.crm_running_assignment_rule
		frappe.flags.crm_running_assignment_rule = self.name
		try:
			return super().do_assignment(doc)
		finally:
			frappe.flags.crm_running_assignment_rule = previous
