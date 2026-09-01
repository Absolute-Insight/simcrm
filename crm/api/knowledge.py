# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Settings -> Knowledge: the articles the Assistant may quote.

Reads are open to any CRM user (the doctype's own read permission); writes are
System Manager only, checked here explicitly rather than left to the doctype so
the gate is visible in the endpoint a reviewer reads.
"""

from __future__ import annotations

import frappe
from frappe import _

from crm.knowledge import load_samples
from crm.utils import user_rate_limited

IMPORT_RATE_LIMIT = 6
IMPORT_RATE_SCOPE = "crm_knowledge_import"

FIELDS = ["name", "title", "category", "tags", "product", "available_to_assistant", "body", "modified"]


@frappe.whitelist()
def list_articles() -> dict:
	frappe.has_permission("CRM Knowledge Article", "read", throw=True)
	rows = frappe.get_list(
		"CRM Knowledge Article", fields=FIELDS, order_by="category asc, title asc", limit=1000
	)
	return {"articles": rows}


@frappe.whitelist()
def save_article(doc: dict | str) -> dict:
	"""Insert or update one article. ``doc`` carries ``name`` to update."""
	frappe.only_for("System Manager", True)
	data = frappe.parse_json(doc) if isinstance(doc, str) else dict(doc or {})
	name = data.pop("name", None)
	allowed = {"title", "category", "tags", "product", "available_to_assistant", "body"}
	data = {key: value for key, value in data.items() if key in allowed}
	if name:
		article = frappe.get_doc("CRM Knowledge Article", name)
		article.update(data)
		article.save()
	else:
		article = frappe.get_doc({"doctype": "CRM Knowledge Article", **data})
		article.insert()
	return {key: article.get(key) for key in FIELDS}


@frappe.whitelist()
def delete_article(name: str) -> None:
	frappe.only_for("System Manager", True)
	frappe.delete_doc("CRM Knowledge Article", name)


@frappe.whitelist()
def import_samples() -> dict:
	"""Load the shipped sample pack, skipping titles that already exist.

	Idempotent by title (case-insensitive) so a second press adds nothing, and
	an admin who edited a sample keeps their edit rather than getting a twin.
	"""
	frappe.only_for("System Manager", True)
	if user_rate_limited(IMPORT_RATE_SCOPE, IMPORT_RATE_LIMIT):
		frappe.throw(_("Too many imports in a minute. Try again shortly."), frappe.ValidationError)

	existing = {
		(title or "").strip().lower() for title in frappe.get_all("CRM Knowledge Article", pluck="title")
	}
	imported = skipped = 0
	for sample in load_samples():
		if sample["title"].strip().lower() in existing:
			skipped += 1
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Knowledge Article",
				"title": sample["title"],
				"category": sample["category"],
				"tags": sample["tags"],
				"product": sample["product"] or None,
				"available_to_assistant": 1,
				"body": sample["content"],
			}
		).insert()
		existing.add(sample["title"].strip().lower())
		imported += 1
	return {"imported": imported, "skipped": skipped}
