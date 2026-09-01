# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the Assistant may say. Curated by administrators in Settings -> Knowledge.

Content here is trusted the way the shipped help articles are -- an
administrator wrote it -- but it reaches a rep only as text inside a model
answer, never as HTML. See ``crm.agent.api.ask_assistant``.
"""

from frappe.model.document import Document


class CRMKnowledgeArticle(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		self.category = (self.category or "").strip()
		self.tags = ", ".join(tag.strip() for tag in (self.tags or "").split(",") if tag.strip())
