"""Carry the Acumatica in-flight markers out of the cache redis into the ERP write ledger.

Until this release an unanswered Customer or SalesOrder PUT left its marker in redis
(``acumatica_inflight::<Entity>::<docname>``); from this release the code reads only
the CRM ERP Write table. A site upgraded while a push is unanswered would otherwise
forget it, and the next push or click would send a second customer or order into the
client's ERP. So every live marker becomes an open ledger row.

Idempotent: a target that already has an open row is left as it is. With redis empty,
or unreachable, it does nothing. The redis keys are left where they are -- they expire
on their own, and an image rolled back to the previous release still finds them.
"""

import frappe

from crm.fcrm.doctype.crm_erp_write import crm_erp_write as ledger

PREFIX = "acumatica_inflight::"
CARRIED = "carried over from the cache marker at upgrade"


def execute():
	cache = frappe.cache()
	try:
		keys = cache.get_keys(PREFIX)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Acumatica in-flight markers: redis unreadable at upgrade")
		return
	site_prefix = cache.make_key("")
	for raw_key in keys or []:
		key = frappe.safe_decode(raw_key)
		key = (
			key[len(frappe.safe_decode(site_prefix)) :]
			if key.startswith(frappe.safe_decode(site_prefix))
			else key
		)
		target = key[len(PREFIX) :] if key.startswith(PREFIX) else None
		if not target:
			continue
		kind, _sep, reference = target.partition("::")
		if kind not in ledger.REFERENCE_DOCTYPES or not reference:
			# the customer-push sweep's throttle and bookmark: not markers
			continue
		value = cache.get_value(key, use_local_cache=False)
		marker = _marker(kind, value)
		if marker is None or _settled(kind, reference):
			continue
		if ledger.acquire(target, marker):
			ledger.record_unknown(target, CARRIED)
			print(f"Carried the in-flight Acumatica marker for {target} into CRM ERP Write")


def _marker(kind: str, value):
	if not value:
		return None
	if kind == "CustomerContact":
		return {"contact": value} if isinstance(value, str) else None
	if kind == "Customer":
		from crm.integrations.acumatica.outbound import _read_marker

		return _read_marker(value)
	# SalesOrder: a bare timestamp
	try:
		return {"sent_at": float(value)}
	except (TypeError, ValueError):
		# no time to wait out: the settle window counts as over, and the retry still
		# looks for the order before sending another
		return {"sent_at": 0}


def _settled(kind: str, reference: str) -> bool:
	"""Whether the outcome reached the record after all -- then there is no write to guard."""
	if kind == "Customer":
		linked = frappe.db.get_value("CRM Organization", reference, ["acumatica_id", "acumatica_noteid"])
		return bool(linked and any(linked))
	if kind == "SalesOrder" and frappe.db.has_column("CRM Deal", "acumatica_sales_quote"):
		return bool(frappe.db.get_value("CRM Deal", reference, "acumatica_sales_quote"))
	return False
