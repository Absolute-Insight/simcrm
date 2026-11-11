"""ERPNext's company restriction on Item, as the CRM catalogue has to honour it.

ERPNext is installed on the release lane only, so none of this may need it: the
Item side is stood in for by plain dicts and patched lookups. What is pinned
here is our half of the contract -- which Items count as closed to the CRM's
company, and what each sync path does about one.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.erpnext import item as item_hooks
from crm.integrations.erpnext import utils

OURS = "Vectora Trading"
THEIRS = "Other Co"


def _item(restricted=0, companies=(), **extra):
	return frappe._dict(
		name="ITM-R",
		item_code="ITM-R",
		item_name="Restricted Widget",
		stock_uom="Nos",
		standard_rate=10,
		image=None,
		disabled=0,
		description="d",
		flags=frappe._dict(),
		restrict_to_companies=restricted,
		allowed_companies=[frappe._dict(company=company) for company in companies],
		**extra,
	)


class _SavedItem(frappe._dict):
	"""An Item with the row it replaced, as a document mid-save carries it."""

	def get_doc_before_save(self):
		return self.before


class TestItemOpenToCompany(FrappeTestCase):
	def test_an_unrestricted_item_is_open_to_everyone(self):
		self.assertTrue(utils.item_open_to_company(_item(), OURS))
		self.assertTrue(utils.item_open_to_company(_item(), None))

	def test_a_restricted_item_is_open_only_to_its_listed_companies(self):
		self.assertTrue(utils.item_open_to_company(_item(1, [THEIRS, OURS]), OURS))
		self.assertFalse(utils.item_open_to_company(_item(1, [THEIRS]), OURS))

	def test_a_restricted_item_is_closed_when_no_company_is_configured(self):
		self.assertFalse(utils.item_open_to_company(_item(1, [THEIRS]), None))

	def test_stale_company_rows_do_not_restrict_an_item_that_is_no_longer_restricted(self):
		"""ERPNext clears the rows on save, but only the checkbox is the rule."""
		self.assertTrue(utils.item_open_to_company(_item(0, [THEIRS]), OURS))

	def test_an_erpnext_without_the_feature_restricts_nothing(self):
		legacy = frappe._dict(name="ITM-OLD")
		self.assertTrue(utils.item_open_to_company(legacy, OURS))


class TestItemsClosedToCrm(FrappeTestCase):
	"""The set-based lookup, with ERPNext's two tables stood in for."""

	def _closed(self, item_codes, restricted, allowed, company=OURS, has_field=True):
		calls = []

		def get_all(doctype, **kwargs):
			calls.append((doctype, kwargs))
			return list(restricted if doctype == "Item" else allowed)

		meta = frappe._dict(has_field=lambda fieldname: has_field)
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe, "get_all", side_effect=get_all),
			patch.object(utils, "crm_company", return_value=company),
		):
			return utils.items_closed_to_crm(item_codes), calls

	def test_restricted_items_that_do_not_list_our_company_are_closed(self):
		closed, calls = self._closed(["A", "B", "C"], restricted=["A", "B"], allowed=["B"])
		self.assertEqual(closed, {"A"})
		self.assertEqual(len(calls), 2, "two queries however many items")
		self.assertEqual(calls[0][1]["filters"]["name"], ("in", ["A", "B", "C"]))
		self.assertEqual(calls[1][1]["filters"]["company"], OURS)
		self.assertEqual(calls[1][1]["filters"]["parentfield"], "allowed_companies")

	def test_every_restricted_item_is_closed_when_no_company_is_configured(self):
		closed, calls = self._closed(None, restricted=["A", "B"], allowed=["B"], company=None)
		self.assertEqual(closed, {"A", "B"})
		self.assertEqual(len(calls), 1)

	def test_nothing_is_closed_on_an_erpnext_without_the_feature(self):
		closed, calls = self._closed(["A"], restricted=["A"], allowed=[], has_field=False)
		self.assertEqual(closed, set())
		self.assertEqual(calls, [])

	def test_no_item_codes_means_no_query(self):
		closed, calls = self._closed([None, ""], restricted=["A"], allowed=[])
		self.assertEqual(closed, set())
		self.assertEqual(calls, [])

	def test_nothing_is_closed_where_erpnext_is_not_installed(self):
		with patch.object(frappe.db, "exists", return_value=False):
			self.assertEqual(utils.items_closed_to_crm(["A"]), set())


class TestItemHooksHonourTheRestriction(FrappeTestCase):
	def _patched(self, company=OURS):
		return (
			patch.object(item_hooks, "should_sync", return_value=True),
			patch.object(item_hooks, "crm_company", return_value=company),
			patch.object(item_hooks, "get_item_price_rate", return_value=None),
		)

	def test_a_closed_item_is_not_mirrored_on_insert(self):
		sync, company, rate = self._patched()
		with sync, company, rate, patch.object(item_hooks, "_create_product") as create:
			item_hooks.after_insert(_item(1, [THEIRS]))
		create.assert_not_called()

	def test_an_open_item_is_still_mirrored_on_insert(self):
		sync, company, rate = self._patched()
		with (
			sync,
			company,
			rate,
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(item_hooks, "_create_product") as create,
		):
			item_hooks.after_insert(_item(1, [OURS]))
		create.assert_called_once()

	def test_a_closed_item_switches_its_product_off(self):
		sync, company, rate = self._patched()
		with sync, company, rate:
			self.assertEqual(item_hooks._catalogue_data(_item(1, [THEIRS]))["disabled"], 1)
			self.assertEqual(item_hooks._catalogue_data(_item(1, [OURS]))["disabled"], 0)

	def test_an_open_item_keeps_its_own_disabled_flag(self):
		sync, company, rate = self._patched()
		with sync, company, rate:
			own = _item()
			own.disabled = 1
			self.assertEqual(item_hooks._catalogue_data(own)["disabled"], 1)

	def test_lifting_the_restriction_creates_the_product_the_insert_skipped(self):
		doc = _SavedItem(_item(1, [THEIRS, OURS]), before=_item(1, [THEIRS]))
		sync, company, rate = self._patched()
		with (
			sync,
			company,
			rate,
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(item_hooks, "_create_product") as create,
		):
			item_hooks.on_update(doc)
		create.assert_called_once_with(doc)

	def test_an_ordinary_save_of_an_unmirrored_item_creates_nothing(self):
		"""An Item made while the sync was off is the reconciliation's to pick up."""
		doc = _SavedItem(_item(), before=_item())
		sync, company, rate = self._patched()
		with (
			sync,
			company,
			rate,
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(item_hooks, "_create_product") as create,
		):
			item_hooks.on_update(doc)
		create.assert_not_called()

	def test_a_save_that_leaves_the_item_closed_creates_nothing(self):
		doc = _SavedItem(_item(1, [THEIRS]), before=_item(1, [THEIRS]))
		sync, company, rate = self._patched()
		with (
			sync,
			company,
			rate,
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(item_hooks, "_create_product") as create,
		):
			item_hooks.on_update(doc)
		create.assert_not_called()


class TestProductPushSkipsAClosedItem(FrappeTestCase):
	def test_nothing_is_pushed_to_an_item_closed_to_our_company(self):
		"""The mirror disabled the product; pushing that back would disable the
		Item for the companies that do sell it."""
		from crm.fcrm.doctype.crm_product import crm_product

		product = frappe._dict(name="P-1", erpnext_item_code="ITM-R", product_name="X", disabled=1)
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(crm_product, "items_closed_to_crm", return_value={"ITM-R"}) as closed,
			patch.object(frappe.db, "get_value") as read_item,
			patch.object(frappe, "get_doc") as load_item,
		):
			crm_product._push_to_item(product)
		closed.assert_called_once_with(["ITM-R"])
		read_item.assert_not_called()
		load_item.assert_not_called()


class TestReconciliationSkipsClosedItems(FrappeTestCase):
	def _run(self, items, products, closed):
		from crm.fcrm.doctype.crm_product import reconcile_job

		summary = reconcile_job._initial_summary()
		with (
			patch.object(reconcile_job, "items_closed_to_crm", return_value=closed),
			patch.object(reconcile_job, "_sync_item_to_product") as sync,
			patch.object(frappe.db, "set_value") as set_value,
		):
			reconcile_job._sync_items_to_products(items, products, summary)
		return summary, sync, set_value

	def test_a_closed_item_is_neither_created_nor_linked(self):
		items = {"A": {"item_code": "A"}, "B": {"item_code": "B"}}
		products = {"B": {"name": "B", "product_code": "B", "erpnext_item_code": None, "disabled": 0}}
		summary, sync, set_value = self._run(items, products, closed={"B"})
		sync.assert_called_once_with(items["A"], None, summary)
		set_value.assert_not_called()
		self.assertEqual(summary["closed_to_crm_company"], 1)

	def test_a_product_already_mirroring_a_closed_item_is_switched_off(self):
		items = {"B": {"item_code": "B"}}
		products = {"B": {"name": "B", "product_code": "B", "erpnext_item_code": "B", "disabled": 0}}
		_summary, sync, set_value = self._run(items, products, closed={"B"})
		sync.assert_not_called()
		set_value.assert_called_once_with("CRM Product", "B", "disabled", 1)

	def test_a_product_already_off_is_not_rewritten(self):
		items = {"B": {"item_code": "B"}}
		products = {"B": {"name": "B", "product_code": "B", "erpnext_item_code": "B", "disabled": 1}}
		_summary, _sync, set_value = self._run(items, products, closed={"B"})
		set_value.assert_not_called()


class TestQuotationPrefillSkipsClosedItems(FrappeTestCase):
	def _item_codes_for(self, product_codes, linked, closed, has_field=True):
		from crm.fcrm.doctype.erpnext_crm_settings import erpnext_crm_settings as settings

		meta = frappe._dict(has_field=lambda fieldname: has_field)
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe, "get_all", return_value=linked) as get_all,
			patch.object(utils, "items_closed_to_crm", return_value=closed),
		):
			return settings._item_codes_for(product_codes), get_all

	def test_a_closed_item_is_left_out_and_the_rest_prefill(self):
		codes, get_all = self._item_codes_for(
			["P-1", "P-2", "P-1"], linked=[("P-1", "ITM-1"), ("P-2", "ITM-2")], closed={"ITM-2"}
		)
		self.assertEqual(codes, {"P-1": "ITM-1"})
		get_all.assert_called_once()

	def test_no_lookup_before_the_integration_has_made_its_link_field(self):
		codes, get_all = self._item_codes_for(["P-1"], linked=[], closed=set(), has_field=False)
		self.assertEqual(codes, {})
		get_all.assert_not_called()

	def test_a_deal_with_no_products_asks_nothing(self):
		codes, get_all = self._item_codes_for([], linked=[], closed=set())
		self.assertEqual(codes, {})
		get_all.assert_not_called()
