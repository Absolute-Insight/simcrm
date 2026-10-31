# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# A deal whose quote ran past its validity. Not a close: the customer can still
# accept or decline, so the deal can go on to Won or Lost, and Acumatica's outcome
# still closes it. "On Hold" keeps it out of the weighted open pipeline (Open and
# Ongoing) without counting it as lost anywhere.
EXPIRED = "Expired"
EXPIRED_DEFAULTS = {"color": "orange", "type": "On Hold", "probability": 10}


class CRMDealStatus(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		color: DF.Literal[
			"black",
			"gray",
			"blue",
			"green",
			"red",
			"pink",
			"orange",
			"amber",
			"yellow",
			"cyan",
			"teal",
			"violet",
			"purple",
		]
		deal_status: DF.Data
		position: DF.Int
		probability: DF.Percent
		type: DF.Literal["Open", "Ongoing", "On Hold", "Won", "Lost"]
	# end: auto-generated types

	pass


def ensure_expired_status() -> str:
	"""Create the Expired deal status if the site lacks it; return its name.

	Placed just before the first Won/Lost status, so the kanban shows it after
	the working stages rather than after Lost. Statuses at or past that point
	move down one.
	"""
	if frappe.db.exists("CRM Deal Status", EXPIRED):
		return EXPIRED
	closed = frappe.get_all(
		"CRM Deal Status",
		filters={"type": ["in", ["Won", "Lost"]]},
		fields=["position"],
		order_by="position asc",
		limit=1,
	)
	if closed:
		position = closed[0].position or 0
		Status = frappe.qb.DocType("CRM Deal Status")
		frappe.qb.update(Status).set(Status.position, Status.position + 1).where(
			Status.position >= position
		).run()
	else:
		position = (frappe.db.get_value("CRM Deal Status", {}, "max(position)") or 0) + 1
	frappe.get_doc(
		{"doctype": "CRM Deal Status", "deal_status": EXPIRED, "position": position, **EXPIRED_DEFAULTS}
	).insert(ignore_permissions=True)
	return EXPIRED
