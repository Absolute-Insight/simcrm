# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The in-app help center's endpoint.

Content lives in ``crm/help/articles`` and ships with the app — see
``crm.help``. This endpoint only serializes it: no aggregation, no state, and
deliberately no per-article endpoint, because the whole set is a few tens of
kilobytes and the client searches it locally.
"""

from __future__ import annotations

import frappe

from crm.help import CATEGORY_ORDER, load_articles


@frappe.whitelist()
def get_articles() -> dict:
	"""Every help article, with the category display order.

	Any authenticated user may read the manual; there is nothing here that is
	not visible in the UI it documents.
	"""
	return {"categories": CATEGORY_ORDER, "articles": load_articles()}
