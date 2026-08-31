import frappe


def execute():
	"""Make ZAR selectable. The dashboard-currency picker (and every other
	Currency link) only offers enabled currencies, and frappe ships ZAR
	disabled. Idempotent; creates the row for sites whose fixture predates it."""
	if frappe.db.exists("Currency", "ZAR"):
		frappe.db.set_value("Currency", "ZAR", "enabled", 1)
		return
	frappe.get_doc(
		{
			"doctype": "Currency",
			"currency_name": "ZAR",
			"enabled": 1,
			"fraction": "Cent",
			"fraction_units": 100,
			"smallest_currency_fraction_value": 0.01,
			"symbol": "R",
			"number_format": "#,###.##",
		}
	).insert(ignore_permissions=True)
