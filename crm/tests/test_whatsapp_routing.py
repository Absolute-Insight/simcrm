"""Which record an inbound WhatsApp number lands on.

CRM rows only, so this runs on a site without frappe_whatsapp too. Meta sends
"27825550148"; the CRM holds whatever a rep typed.
"""

import frappe
from frappe.tests import IntegrationTestCase

from crm.integrations.api import lookup_contact_lead_or_deal_from_number
from crm.utils import canonical_whatsapp_number, is_same_whatsapp_number

INBOUND = "27825550148"


def make_lead(**fields):
	lead = frappe.new_doc("CRM Lead")
	lead.update({"first_name": "Thandi", **fields})
	return lead.insert(ignore_permissions=True)


def make_contact(number):
	contact = frappe.new_doc("Contact")
	contact.first_name = "Sipho " + frappe.generate_hash(length=6)
	contact.append("phone_nos", {"phone": number, "is_primary_mobile_no": 1})
	return contact.insert(ignore_permissions=True)


def make_deal(contacts=(), status=None, primary=None, **fields):
	deal = frappe.new_doc("CRM Deal")
	deal.update({"organization": None, **fields})
	if status:
		deal.status = status
	for contact in contacts:
		deal.append("contacts", {"contact": contact.name, "is_primary": contact is primary})
	deal.flags.ignore_mandatory = True
	return deal.insert(ignore_permissions=True, ignore_mandatory=True)


class TestNumberNormalisation(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("System Settings", "country", "South Africa")

	def tearDown(self):
		frappe.db.rollback()

	def test_every_south_african_spelling_is_one_number(self):
		for spelling in ("0825550148", "082 555 0148", "27825550148", "+27825550148", "+27 82 555-0148"):
			with self.subTest(spelling):
				self.assertEqual(canonical_whatsapp_number(spelling), INBOUND)

	def test_a_foreign_number_keeps_its_own_country(self):
		self.assertEqual(canonical_whatsapp_number("+447911123456"), "447911123456")

	def test_rubbish_is_not_a_number(self):
		self.assertIsNone(canonical_whatsapp_number("not a number"))
		self.assertIsNone(canonical_whatsapp_number(""))
		self.assertIsNone(canonical_whatsapp_number(None))

	def test_a_stored_number_matches_in_every_spelling(self):
		for stored in ("0825550148", "082 555 0148", "27825550148", "+27 82 555 0148", "0027825550148"):
			with self.subTest(stored):
				self.assertTrue(is_same_whatsapp_number(stored, INBOUND))

	def test_a_number_that_merely_contains_the_digits_does_not_match(self):
		self.assertFalse(is_same_whatsapp_number("+44825550148", INBOUND))
		self.assertFalse(is_same_whatsapp_number("825550149", INBOUND))


class TestInboundRouting(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("System Settings", "country", "South Africa")

	def tearDown(self):
		frappe.db.rollback()

	def test_a_lead_stored_with_a_local_number_is_found(self):
		lead = make_lead(mobile_no="082 555 0148")
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (lead.name, "CRM Lead"))

	def test_a_leads_phone_field_is_searched(self):
		lead = make_lead(phone="0825550148")
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (lead.name, "CRM Lead"))

	def test_a_converted_lead_is_not_a_home_for_the_message(self):
		make_lead(mobile_no="0825550148", converted=1)
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (None, None))

	def test_a_non_primary_deal_contact_matches(self):
		boss, buyer = make_contact("0821112222"), make_contact("0825550148")
		deal = make_deal([boss, buyer], primary=boss)
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (deal.name, "CRM Deal"))

	def test_a_contact_on_no_record_is_no_home_either(self):
		"""A thread filed on a bare Contact shows up nowhere in the app."""
		make_contact("0825550148")
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (None, None))

	def test_an_open_deal_beats_a_lost_one_and_a_lead(self):
		contact = make_contact("+27825550148")
		lost = make_deal([contact], primary=contact)
		frappe.db.set_value("CRM Deal", lost.name, "status", "Lost")
		make_lead(mobile_no="0825550148")
		open_deal = make_deal([contact], primary=contact)
		frappe.db.set_value(
			"CRM Deal", open_deal.name, "modified", "2001-01-01 00:00:00", update_modified=False
		)
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (open_deal.name, "CRM Deal"))

	def test_a_closed_deal_still_beats_having_no_record(self):
		contact = make_contact("0825550148")
		lost = make_deal([contact], primary=contact)
		frappe.db.set_value("CRM Deal", lost.name, "status", "Lost")
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (lost.name, "CRM Deal"))

	def test_the_receiving_reps_own_record_wins_a_tie(self):
		make_lead(mobile_no="0825550148", lead_owner="Administrator")
		mine = make_lead(mobile_no="0825550148")
		frappe.db.set_value(
			"CRM Lead",
			mine.name,
			{"lead_owner": "rep@example.com", "modified": "2001-01-01"},
			update_modified=False,
		)
		self.assertEqual(
			lookup_contact_lead_or_deal_from_number(INBOUND, prefer_user="rep@example.com"),
			(mine.name, "CRM Lead"),
		)

	def test_the_same_data_always_gives_the_same_record(self):
		one, two = make_lead(mobile_no="0825550148"), make_lead(mobile_no="0825550148")
		for lead in (one, two):
			frappe.db.set_value(
				"CRM Lead", lead.name, "modified", "2020-01-01 00:00:00", update_modified=False
			)
		first = lookup_contact_lead_or_deal_from_number(INBOUND)
		self.assertEqual(first, (min(one.name, two.name), "CRM Lead"))
		self.assertEqual(first, lookup_contact_lead_or_deal_from_number(INBOUND))

	def test_an_unknown_number_finds_nothing(self):
		self.assertEqual(lookup_contact_lead_or_deal_from_number("27825550999"), (None, None))


class TestNumberSpellings(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("System Settings", "country", "South Africa")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_bracketed_trunk_zero_is_the_same_number(self):
		self.assertTrue(is_same_whatsapp_number("+27 (0)82 555 0148", INBOUND))

	def test_dots_slashes_and_nbsp_reach_the_sql_match(self):
		for stored in ("082.555.0148", "082/555/0148", "082 555 0148", "+27 (0)82 555 0148"):
			with self.subTest(stored):
				lead = make_lead()
				# as an import writes it: the Phone field's own validator is not in the way
				frappe.db.set_value("CRM Lead", lead.name, "mobile_no", stored)
				self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (lead.name, "CRM Lead"))
				frappe.db.delete("CRM Lead", lead.name)

	def test_a_foreign_number_does_not_match_a_local_looking_one(self):
		self.assertFalse(is_same_whatsapp_number("0612345678", "33612345678"))
		self.assertFalse(is_same_whatsapp_number("083 123 4567", "353831234567"))

	def test_on_a_site_in_that_country_the_local_form_matches(self):
		frappe.db.set_single_value("System Settings", "country", "France")
		self.assertTrue(is_same_whatsapp_number("0612345678", "33612345678"))

	def test_an_italian_leading_zero_matches_itself(self):
		self.assertTrue(is_same_whatsapp_number("+390612345678", "390612345678"))
		self.assertTrue(is_same_whatsapp_number("390612345678", "390612345678"))


class TestBareContact(IntegrationTestCase):
	def setUp(self):
		frappe.db.set_single_value("System Settings", "country", "South Africa")

	def tearDown(self):
		frappe.db.rollback()

	def test_a_contacts_message_lands_on_an_open_deal_of_their_organization(self):
		org = frappe.new_doc("CRM Organization")
		org.organization_name = "Acme " + frappe.generate_hash(length=6)
		org.insert(ignore_permissions=True)
		contact = make_contact("0825550148")
		frappe.db.set_value("Contact", contact.name, "company_name", org.name)
		deal = make_deal(organization=org.name)
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (deal.name, "CRM Deal"))

	def test_a_contact_with_a_closed_org_deal_stays_recordless(self):
		org = frappe.new_doc("CRM Organization")
		org.organization_name = "Acme " + frappe.generate_hash(length=6)
		org.insert(ignore_permissions=True)
		contact = make_contact("0825550148")
		frappe.db.set_value("Contact", contact.name, "company_name", org.name)
		deal = make_deal(organization=org.name)
		frappe.db.set_value("CRM Deal", deal.name, "status", "Lost")
		self.assertEqual(lookup_contact_lead_or_deal_from_number(INBOUND), (None, None))
