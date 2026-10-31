# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Max, Min

# A deal whose quote ran past its validity. Not a close: the customer can still
# accept or decline, so the deal can go on to Won or Lost, and Acumatica's outcome
# still closes it. "On Hold" keeps it out of the weighted open pipeline (Open and
# Ongoing) without counting it as lost anywhere; the open tiles and the forecast,
# which do take On Hold, leave it out by name (crm.api.dashboard.still_open).
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
	move down one. Where the closed statuses have no position to go by, it goes
	last.
	"""
	if frappe.db.exists("CRM Deal Status", EXPIRED):
		return EXPIRED
	Status = frappe.qb.DocType("CRM Deal Status")
	first_closed = (
		frappe.qb.from_(Status)
		.select(Min(Status.position))
		.where(Status.type.isin(["Won", "Lost"]) & (Status.position > 0))
		.run()[0][0]
	)
	if first_closed:
		position = first_closed
		frappe.qb.update(Status).set(Status.position, Status.position + 1).where(
			Status.position >= position
		).run()
	else:
		position = (frappe.qb.from_(Status).select(Max(Status.position)).run()[0][0] or 0) + 1
	frappe.get_doc(
		{"doctype": "CRM Deal Status", "deal_status": EXPIRED, "position": position, **EXPIRED_DEFAULTS}
	).insert(ignore_permissions=True)
	return EXPIRED


def expired_status_is_usable() -> bool:
	"""False on a site whose own status called Expired is a closing one.

	Sending quotes there would win or lose deals, which is the thing this status
	exists not to do, so the sweep stands down rather than guess.
	"""
	return frappe.db.get_value("CRM Deal Status", EXPIRED, "type") not in ("Won", "Lost")
