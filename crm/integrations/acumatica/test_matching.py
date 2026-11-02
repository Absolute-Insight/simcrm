from unittest import TestCase

from crm.integrations.acumatica.matching import (
	name_match,
	normalise_name,
	normalise_vat,
	state_code,
)


class TestNormaliseName(TestCase):
	def test_legal_forms_punctuation_and_case_go(self):
		self.assertEqual(normalise_name("SBS Engineering - Merensky (Pty) Ltd"), "sbs engineering merensky")
		self.assertEqual(normalise_name("SBS ENGINEERING MERENSKY"), "sbs engineering merensky")

	def test_ampersand_reads_as_and(self):
		self.assertEqual(normalise_name("Smith & Sons CC"), normalise_name("Smith and Sons"))

	def test_trailing_cod_and_holdings_go(self):
		self.assertEqual(normalise_name("Acme Holdings - COD"), "acme")
		self.assertEqual(normalise_name("Proprietary Limited"), "")


class TestNameMatch(TestCase):
	def m(self, a, b):
		return name_match(normalise_name(a), normalise_name(b))

	def test_same_business_in_two_spellings(self):
		self.assertEqual(
			self.m("SBS Engineering Merensky", "SBS Engineering - Merensky (Pty) Ltd"), "same name"
		)
		self.assertEqual(self.m("Merensky SBS Engineering", "SBS Engineering Merensky"), "same name")

	def test_a_typo_is_similar(self):
		self.assertEqual(self.m("SBS Engineerng Merensky", "SBS Engineering Merensky"), "similar name")

	def test_a_second_site_of_a_group_is_flagged_not_waved_through(self):
		self.assertEqual(
			self.m("Bearing Man Group - Mozambique", "Bearing Man Group (Pty) Ltd"), "similar name"
		)

	def test_different_businesses_do_not_match(self):
		self.assertIsNone(self.m("Acme Engineering", "Apex Valves"))
		self.assertIsNone(self.m("Acme Engineering", "Acme Engineers"))
		# one shared word is not a group
		self.assertIsNone(self.m("Kloof Mining", "Kloof"))

	def test_empty_names_never_match(self):
		self.assertIsNone(name_match("", ""))
		self.assertIsNone(self.m("(Pty) Ltd", "Pty Ltd"))


class TestNormaliseVat(TestCase):
	def test_formatting_is_ignored(self):
		self.assertEqual(normalise_vat("VAT 4123 456-789"), "4123456789")

	def test_too_short_to_identify_anyone(self):
		self.assertEqual(normalise_vat("n/a"), "")
		self.assertEqual(normalise_vat("123"), "")
		self.assertEqual(normalise_vat(None), "")


class TestStateCode(TestCase):
	def test_za_provinces_in_the_spellings_people_type(self):
		cases = {
			"Gauteng": "GP",
			"GAUTENG": "GP",
			"GP - Gauteng": "GP",
			"gp": "GP",
			"North West": "NW",
			"North-West Province": "NW",
			"KwaZulu-Natal": "KZN",
			"Kwazulu Natal": "KZN",
			"KZN": "KZN",
			"Mpumalanga": "MP",
			"Limpopo": "LP",
			"Western Cape": "WC",
			"Free State": "FS",
			"Eastern Cape": "EC",
			"Northern Cape": "NC",
			"Gauteng (GP)": "GP",
		}
		for raw, code in cases.items():
			self.assertEqual(state_code(raw, "ZA"), code, raw)

	def test_an_unknown_za_value_is_left_out(self):
		self.assertIsNone(state_code("Johannesburg", "ZA"))
		self.assertIsNone(state_code("", "ZA"))
		self.assertIsNone(state_code(None, "za"))

	def test_elsewhere_only_a_code_is_sent(self):
		self.assertEqual(state_code("tx", "US"), "TX")
		self.assertEqual(state_code("NSW", "AU"), "NSW")
		self.assertIsNone(state_code("Maputo Province", "MZ"))
		self.assertIsNone(state_code("Gauteng", "BW"))
