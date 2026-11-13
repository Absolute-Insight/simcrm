# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The reference-sheet layer: finding the row, and refusing a figure that is not on it.

Pure -- no site, no model. The rows are shaped like the MBP sheets that
prompted the feature (flange drilling, bolt sets, line sizes), because the
traps are in their shape: a 2" bolt on a 36" flange, a PN16 that is also
1600 kPa, a decimal comma.
"""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.agent import reference


def drilling(size_mm, inch, standard, cls, search, **cells):
	labels = {
		"od": ("Flange OD", "mm"),
		"pcd": ("PCD (bolt circle diameter)", "mm"),
		"holes": ("Number of bolt holes", ""),
		"hole_dia": ("Bolt hole diameter (d1)", "mm"),
		"bolt": ("Bolt size", ""),
	}
	out = []
	for key, value in cells.items():
		label, unit = labels[key]
		status, value = (reference.QUESTIONED, value[1:]) if str(value).startswith("?") else ("ok", value)
		out.append(
			{"label": label, "value": str(value), "unit": unit, "status": status, "bbox": [1, 2, 3, 4]}
		)
	return {
		"name": f"d-{size_mm}-{cls}",
		"sheet_title": "Flange Drilling Tables",
		"page": 2,
		"section": "Flange drilling",
		"label": f'{size_mm} mm ({inch}") · {standard} {cls}',
		"search": f'{size_mm} mm {inch}" flange drilling {search}',
		"cells": out,
	}


def bolt_set(size_mm, inch, standard, value, search):
	quantity, bolt, length = value.replace(" Off ", " ").replace(" x ", " ").split()
	return {
		"name": f"b-{size_mm}-{standard}",
		"sheet_title": "Flange Bolt Dimensions",
		"page": 1,
		"section": "Flange bolts",
		"label": f'{size_mm} mm ({inch}") · {standard}',
		"search": f'{size_mm} mm {inch}" flange bolts bolt set {search}',
		"cells": [
			{"label": "Bolt set", "value": value, "status": "ok"},
			{"label": "Number of bolts", "value": quantity, "status": "ok"},
			{"label": "Bolt size", "value": bolt, "status": "ok"},
			{"label": "Bolt length", "value": length, "unit": "mm", "status": "ok"},
		],
	}


ROWS = [
	drilling(
		150, 6, "SABS 1123", "1600/3", "SABS 1600 kPa PN16", od="285.0", pcd="240.0", holes="8", bolt="M20"
	),
	drilling(
		150, 6, "SABS 1123", "1000/3", "SABS 1000 kPa PN10", od="285.0", pcd="240.0", holes="8", bolt="M16"
	),
	drilling(
		100, 4, "ASME B16.5", "Class 150", "ASME ANSI class 150 150 lb", od="228.6", pcd="190.5", bolt='5/8"'
	),
	drilling(900, 36, "ASME B16.5", "Class 300", "ASME ANSI class 300", od="1270.0", bolt='2"'),
	drilling(450, 18, "SABS 1123", "1600/3", "SABS 1600 kPa PN16", pcd="585.0", hole_dia="?36.0", bolt="M24"),
	bolt_set(150, 6, "SABS 1123 1600 kPa", "8 Off M20 x 75", "SABS 1600 kPa PN16"),
	{
		"name": "line-65",
		"sheet_title": "Line Sizes",
		"page": 1,
		"section": "Line sizes",
		"label": '2 1/2" = 65 mm',
		"search": '2 1/2" 65 mm line size inch to mm',
		"cells": [
			{"label": "Inches", "value": '2 1/2"', "status": "ok"},
			{"label": "Millimetres", "value": "65", "unit": "mm", "status": "ok"},
		],
	},
	{
		"name": "rating-300",
		"sheet_title": "Rating & Bar",
		"page": 1,
		"section": "Pressure ratings",
		"label": "ANSI CLASS 300",
		"search": "ANSI CLASS 300 class 300 rating pressure test",
		"cells": [{"label": "Rated pressure", "value": "51,33 Bar", "status": "ok"}],
	},
]


def labels(rows):
	return [row["label"] for row in rows]


class NormaliseTest(UnitTestCase):
	def test_inches_millimetres_and_ratings_are_spelled_one_way(self):
		self.assertEqual(reference.tokens('6"') & {"6in"}, {"6in"})
		self.assertIn("6in", reference.tokens("a 6 inch flange"))
		self.assertIn("1-1/2in", reference.tokens('1 1/2" pipe'))
		self.assertIn("1-1/2in", reference.tokens("1½” pipe"))
		self.assertIn("150mm", reference.tokens("DN150"))
		self.assertIn("pn16", reference.tokens("PN 16"))
		self.assertIn("class150", reference.tokens("150 lb"))
		self.assertIn("1000kpa", reference.tokens("1,000 kPa"))
		self.assertIn("6in", reference.tokens("a 6-inch flange"))
		self.assertIn("150mm", reference.tokens("150NB"))
		self.assertIn("150mm", reference.tokens("150 NB pipe"))

	def test_a_tagged_number_also_counts_bare(self):
		# "SABS 1600" must find the row the sheet labels "1600 kPa"
		self.assertTrue({"1600kpa", "1600"} <= reference.tokens("1600 kPa"))

	def test_in_before_a_unit_is_a_word_not_an_inch_mark(self):
		"""Audit H-05: "class 600 in bar" asked for a 600" flange and lost class600."""
		for question, meant, not_meant in (
			("rated pressure of class 600 in bar", {"class600"}, {"600in"}),
			("bolts for DN150 PN 16 in mm", {"pn16", "150mm"}, {"16in"}),
			("PCD of 6 inch class 150 in mm", {"6in", "class150"}, {"150in"}),
			("what is 150 in inches", set(), {"150in"}),
			("1600 in kPa", set(), {"1600in"}),
			# a rating's number is not a size whatever follows "in"
			("is class 300 in stock", {"class300"}, {"300in"}),
			("PN 16 in the catalogue", {"pn16"}, {"16in"}),
		):
			with self.subTest(question=question):
				found = reference.tokens(question)
				self.assertTrue(meant <= found, sorted(found))
				self.assertFalse(not_meant & found, sorted(found))
		# a bare "in" after a size is still the inch mark
		self.assertIn("6in", reference.tokens("what is 6 in in mm"))
		self.assertIn("2-1/2in", reference.tokens("2 1/2 in flange"))


class NumbersTest(UnitTestCase):
	def test_a_sign_is_kept_unless_it_is_a_hyphen(self):
		self.assertEqual(reference.numbers("-20ºF to 800ºF"), [{"-20"}, {"800"}])
		self.assertEqual(reference.numbers("15-20 bar"), [{"15"}, {"20"}])
		self.assertEqual(reference.numbers("A182-F1"), [{"182"}, {"1"}])

	def test_a_fraction_is_one_figure(self):
		self.assertEqual(reference.numbers('1 3/8" bolts'), [{"1 3/8"}])
		self.assertEqual(reference.numbers("1-1/2 and 3/8"), [{"1 1/2"}, {"3/8"}])
		self.assertEqual(reference.numbers("1½”"), [{"1 1/2"}])

	def test_commas_are_thousands_or_a_decimal_never_both(self):
		self.assertEqual(reference.numbers("1,000 kPa"), [{"1000"}])
		self.assertEqual(reference.numbers("51,33 Bar"), [{"51.33"}])
		self.assertEqual(reference.numbers("285.0 mm"), [{"285"}])

	def test_a_comma_after_a_leading_zero_is_a_decimal(self):
		"""Audit be_agent-2: "0,125 mm" read as 125 -- a thousands group never
		follows a leading zero. A right answer was refused and "0,125 kPa" passed
		against a row holding 125 kPa."""
		self.assertEqual(reference.numbers("0,125 mm"), reference.numbers("0.125 mm"))
		self.assertEqual(reference.numbers("0,125 mm"), [{".125"}])
		self.assertEqual(reference.numbers("00,500"), [{".5"}])
		# four digits before the comma are not a thousands group either
		self.assertEqual(reference.numbers("1234,567"), [{"1234.567"}])
		self.assertEqual(reference.numbers("1,234,567"), [{"1234567"}])
		self.assertNotIn("0125", reference.normalise("0,125 mm"))
		self.assertIn("1234567", reference.normalise("1,234,567 kPa"))
		row = {
			**ROWS[7],
			"cells": [
				{"label": "Rated pressure", "value": "125", "unit": "kPa", "status": "ok"},
				{"label": "Gasket", "value": "0.125", "unit": "mm", "status": "ok"},
			],
		}
		self.assertEqual(reference.verify("The gasket is 0,125 mm.", [row], [row])[0], [row])
		row["cells"].pop()
		self.assertIsNone(reference.verify("It is rated 0,125 kPa.", [row], [row])[0])

	def test_thousands_dots_before_a_decimal_comma(self):
		self.assertEqual(reference.numbers("1.234,56"), [{"1234.56"}])
		self.assertEqual(reference.numbers("12.345.678,9 kPa"), [{"12345678.9"}])
		self.assertEqual(reference.numbers("001.234,5"), [{"1234.5"}])
		# a plain decimal, and a decimal comma, are untouched
		self.assertEqual(reference.numbers("1.234 and 51,33"), [{"1.234"}, {"51.33"}])

	def test_a_thousands_comma_before_a_decimal_is_still_thousands(self):
		"""Audit L-39: "1,270.0" read as 1.270 refused a correct answer."""
		self.assertEqual(reference.numbers("1,270.0 mm"), [{"1270"}])
		self.assertEqual(reference.numbers("12,500.5"), [{"12500.5"}])
		self.assertEqual(reference.numbers("1,234,567.25"), [{"1234567.25"}])
		self.assertEqual(reference.numbers("51,33 Bar"), [{"51.33"}])
		used, missing = reference.verify("The OD is 1,270.0 mm.", ROWS, [ROWS[3]])
		self.assertEqual((used, missing), ([ROWS[3]], []))

	def test_mixed_and_signed_figures_do_not_support_their_parts(self):
		sheet = [{**ROWS[2], "cells": [{"label": "Bolt size", "value": '1 3/8"', "status": "ok"}]}]
		used, _ = reference.verify('Use 3/8" bolts.', sheet, sheet)
		self.assertIsNone(used)


class SelectEntriesTest(UnitTestCase):
	def test_the_named_size_and_class_come_first(self):
		picked = reference.select_entries("Which bolts for a 6 inch SABS 1600 flange?", ROWS)
		self.assertIn(picked[0]["name"], {"b-150-SABS 1123 1600 kPa", "d-150-1600/3"})
		self.assertTrue(all("150 mm" in row["label"] for row in picked))

	def test_a_hyphenated_or_nb_size_still_gates(self):
		for question in ("bolts for a 6-inch PN16 flange", "bolts for 150NB PN16", "PCD 100 NB class 150"):
			with self.subTest(question=question):
				picked = reference.select_entries(question, ROWS)
				size = "100 mm" if "100" in question else "150 mm"
				self.assertTrue(picked and all(size in row["label"] for row in picked), labels(picked))

	def test_a_size_in_a_cell_is_not_the_rows_size(self):
		# the 36" class 300 flange takes 2" bolts; a 2" question is not about it
		picked = reference.select_entries("bolt size for 2 inch class 300", ROWS)
		self.assertNotIn("d-900-Class 300", [row["name"] for row in picked])

	def test_a_rating_followed_by_in_and_a_unit_selects_that_rating(self):
		"""Audit H-05: the 16" BS 10 bolt set came back for "DN150 PN 16 in mm"."""
		rows = [
			*ROWS,
			bolt_set(400, 16, "BS 10 Table H", "20 Off M24 x 150", "BS 10 BS10 Table H"),
			{
				**ROWS[7],
				"name": "rating-600",
				"label": "ANSI CLASS 600",
				"search": "ANSI CLASS 600 class 600",
			},
			{**ROWS[7], "name": "rating-pn16", "label": "PN16", "search": "PN16 PN 16 16 bar"},
		]
		picked = reference.select_entries("what is the rated pressure of class 600 in bar", rows)
		self.assertEqual([row["name"] for row in picked][:1], ["rating-600"])
		picked = reference.select_entries("bolts for DN150 PN 16 in mm", rows)
		self.assertTrue(picked and all("150 mm" in row["label"] for row in picked), labels(picked))

	def test_a_short_row_wins_a_conversion_question(self):
		picked = reference.select_entries("what is 2 1/2 inch in mm", ROWS)
		self.assertEqual(labels(picked)[:1], ['2 1/2" = 65 mm'])

	def test_a_bare_in_before_mm_still_asks_for_an_inch_size(self):
		# "1/2 in mm" is "1/2 inch, in mm": the H-05 fix must not read it as the word
		rows = [
			*ROWS,
			{
				**ROWS[6],
				"name": "line-15",
				"label": '1/2" = 15 mm',
				"search": '1/2" 15 mm line size inch to mm',
				"cells": [
					{"label": "Inches", "value": '1/2"', "status": "ok"},
					{"label": "Millimetres", "value": "15", "unit": "mm", "status": "ok"},
				],
			},
		]
		for question, label in (
			("what is 1/2 in mm", '1/2" = 15 mm'),
			("1/2 in mm", '1/2" = 15 mm'),
			("2 1/2 in mm", '2 1/2" = 65 mm'),
			("convert 2 1/2 in cm", '2 1/2" = 65 mm'),
		):
			with self.subTest(question=question):
				self.assertEqual(labels(reference.select_entries(question, rows))[:1], [label])

	def test_one_rare_word_is_enough(self):
		picked = reference.select_entries("what is Millimetres for that?", ROWS)
		self.assertEqual(labels(picked), ['2 1/2" = 65 mm'])

	def test_an_unrelated_question_selects_nothing(self):
		self.assertEqual(reference.select_entries("What are our delivery lead times?", ROWS), [])
		self.assertEqual(reference.select_entries("which flange is best?", ROWS), [])

	def test_a_prebuilt_index_gives_the_same_answer(self):
		question = "PCD of a 4 inch ANSI 150 flange"
		self.assertEqual(
			reference.select_entries(question, ROWS),
			reference.select_entries(question, ROWS, index=reference.build_index(ROWS)),
		)


class VerifyTest(UnitTestCase):
	def test_figures_on_the_cited_row_pass_and_name_it(self):
		row = ROWS[0]
		used, missing = reference.verify("The PCD is 240.0 mm with 8 M20 bolts.", ROWS, [row])
		self.assertEqual((used, missing), ([row], []))

	def test_trailing_zeros_number_words_and_decimal_commas_are_the_same_figure(self):
		used, _ = reference.verify("PCD 240 mm, eight bolts.", ROWS, [ROWS[0]])
		self.assertEqual(used, [ROWS[0]])
		used, _ = reference.verify("Class 300 is rated 51.33 bar.", ROWS, [])
		self.assertEqual(used, [ROWS[7]])

	def test_tens_in_words_are_checked_too(self):
		used, missing = reference.verify("It takes thirty bolts.", ROWS, [ROWS[0]])
		self.assertIsNone(used)
		self.assertEqual(missing, ["30"])

	def test_a_figure_on_no_row_is_refused(self):
		used, missing = reference.verify("The PCD is 241.3 mm.", ROWS, [ROWS[0]])
		self.assertIsNone(used)
		self.assertEqual(missing, ["241.3"])

	def test_one_claim_may_not_mix_two_rows(self):
		# 285.0 and M16 are both on the sheet -- on different rows. Together
		# they describe a flange that is not on it.
		used, _ = reference.verify("The 1600 kPa flange: OD 285.0 mm, M16 bolts.", ROWS, [])
		self.assertIsNone(used)

	def test_a_list_may_take_each_line_from_its_own_row(self):
		answer = "- 1600 kPa: 8 bolts, M20\n- 1000 kPa: 8 bolts, M16"
		used, _ = reference.verify(answer, ROWS, [])
		self.assertEqual([row["name"] for row in used], ["d-150-1600/3", "d-150-1000/3"])

	def test_an_uncited_row_that_holds_the_figure_is_the_real_source(self):
		used, _ = reference.verify("The PCD is 190.5 mm.", ROWS, [ROWS[0]])
		self.assertEqual(used, [ROWS[2]])

	def test_a_questioned_value_is_not_support(self):
		used, missing = reference.verify("The hole is 36.0 mm.", ROWS, [ROWS[4]])
		self.assertIsNone(used)
		self.assertEqual(missing, ["36"])

	def test_the_question_is_not_support(self):
		# "is the PCD 241 mm?" -- a yes must not pass when the row says 240.0
		used, missing = reference.verify("Yes, the PCD is 241 mm.", ROWS, [ROWS[0]])
		self.assertIsNone(used)
		self.assertEqual(missing, ["241"])

	def test_an_article_may_supply_a_figure_but_never_a_withheld_one(self):
		article = ["Stock flanges ship in 3 days. Holes are 36.0 mm."]
		used, _ = reference.verify("The PCD is 240.0 mm and stock ships in 3 days.", ROWS, [ROWS[0]], article)
		self.assertEqual(used, [ROWS[0]])
		used, missing = reference.verify("The 450 mm hole is 36.0 mm.", ROWS, [ROWS[4]], article)
		self.assertIsNone(used)


INCH_ROW = {
	"name": "b-150-asme",
	"sheet_title": "Bolts",
	"page": 1,
	"section": "",
	"label": '150 mm (6") · ASME Class 150',
	"cells": [
		{"label": "Bolts", "value": "4", "status": "ok"},
		{"label": "Bolt size", "value": "5/8", "unit": "in", "status": "ok"},
	],
}


class ReviewBypassTest(UnitTestCase):
	"""Answers that read like the sheet and are not on it -- each found in review."""

	def test_a_proper_fraction_does_not_vouch_for_its_digits(self):
		used, missing = reference.verify('A 6" Class 150 flange takes 8 bolts of 5/8 in.', [INCH_ROW])
		self.assertIsNone(used)
		self.assertEqual(missing, ["8"])

	def test_a_heading_binds_the_lines_under_it(self):
		class150 = {**ROWS[2], "name": "c150", "label": '100 mm (4") · ASME B16.5 Class 150'}
		class300 = {
			**ROWS[2],
			"name": "c300",
			"label": '100 mm (4") · ASME B16.5 Class 300',
			"cells": [{"label": "PCD", "value": "200.0", "unit": "mm", "status": "ok"}],
		}
		rows = [class150, class300]
		used, _ = reference.verify('4" Class 300:\nPCD 190.5 mm', rows)
		self.assertIsNone(used)
		used, _ = reference.verify('4" Class 300:\nPCD 200.0 mm', rows)
		self.assertEqual(used, [class300])
		# a line naming its own row is read as that row
		used, _ = reference.verify('4" flanges:\n- Class 150: PCD 190.5 mm\n- Class 300: PCD 200.0 mm', rows)
		self.assertEqual(used, [class150, class300])

	def test_a_subject_carries_on_whatever_the_heading_looks_like(self):
		a = {
			"name": "a",
			"sheet_title": "Drilling",
			"page": 1,
			"section": "",
			"label": '6" Class 150',
			"cells": [
				{"label": "PCD", "value": "241.3", "unit": "mm", "status": "ok"},
				{"label": "Bolts", "value": "8", "status": "ok"},
			],
		}
		b = {
			**a,
			"name": "b",
			"label": '6" Class 300',
			"cells": [
				{"label": "PCD", "value": "269.9", "unit": "mm", "status": "ok"},
				{"label": "Bolts", "value": "12", "status": "ok"},
			],
		}
		for answer in (
			'**6" Class 300:**\n- PCD 241.3 mm',
			'### 6" Class 300\n- PCD 241.3 mm',
			'6" Class 300\nPCD 241.3 mm',
			'6" Class 300:\n- PCD 241.3 mm on the 6" flange',
			'The 6" Class 300 flange has a PCD of 269.9 mm. It takes 8 bolts.',
			'6" Class 300: PCD 269.9 mm; 8 bolts',
			# markdown's blank line between a heading and its body
			'### 6" Class 300\n\n- PCD 241.3 mm\n- 8 bolts',
			'**6" Class 300:**\n\nPCD 241.3 mm, 8 bolts.',
			'6" Class 300:\n\n- PCD 241.3 mm',
			'6" Class 300: PCD 269.9 mm.\n\nIt takes 8 bolts.',
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [a, b], [b])[0])
		for answer in (
			'6" Class 300: PCD 269.9 mm; 12 bolts',
			'6" flanges:\n- Class 150: PCD 241.3 mm\n- Class 300: PCD 269.9 mm',
			'6" Class 300: PCD 269.9 mm.\n\nClass 150 takes 8 bolts.',
		):
			with self.subTest(answer=answer):
				self.assertIsNotNone(reference.verify(answer, [a, b], [b])[0])

	def test_one_claim_may_not_mix_a_row_and_an_article(self):
		article = ["Standard stud lengths: 65, 75 and 90 mm."]
		used, _ = reference.verify("8 Off M20 x 90", [ROWS[5]], [], article)
		self.assertIsNone(used)
		used, _ = reference.verify("Studs come in 90 mm.", [ROWS[5]], [], article)
		self.assertEqual(used, [])

	def test_a_unicode_minus_keeps_its_sign(self):
		self.assertEqual(reference.numbers("\u221229 \u00baC"), [{"-29"}])
		self.assertEqual(reference.numbers("15\u201320 bar"), [{"15"}, {"20"}])


class NamingNumbersTest(UnitTestCase):
	"""Audit be_agent-1 (A3-3): the numbers that say which row is meant -- its
	size, standard, class, page, a digit in a column's name -- vouched for any
	figure. They name the row; only a confirmed cell is what a column says."""

	ROW = ROWS[0] | {
		"cells": [
			*ROWS[0]["cells"],
			{"label": "Bolt hole diameter (d1)", "value": "22.0", "unit": "mm", "status": "ok"},
		]
	}

	def test_a_naming_number_is_not_a_columns_value(self):
		for answer in (
			"The flange OD is 150 mm.",  # the nominal bore
			'The 6" flange has 6 bolt holes.',  # the inch size
			"It takes 2 bolts.",  # the page
			"The PCD is 1123 mm.",  # SABS 1123
			"Bolt holes are 1 mm.",  # the 1 of "(d1)"
			"It has an OD of 150 mm.",
			"OD: 150 mm",
			"| Flange OD | 150 mm |",
			'The 6" flange has a 150 mm OD.',
			"The OD for this flange is approximately 150 mm.",
			"The PCD (bolt circle diameter) is 150 mm.",
			"Bolt hole diameter (d1): 6 mm",
			"The 150 mm flange has 3 bolt holes.",  # the 3 of 1600/3
			"Flange OD 1600 mm",
			"PCD 150 mm, 8 holes",
			"The bolt size is 6.",
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])

	def test_an_answer_may_still_name_its_row(self):
		for answer in (
			'The 150 mm (6") SABS 1123 1600/3 flange has an OD of 285.0 mm and 8 bolt holes (d1 22.0 mm).',
			"Flange Drilling Tables, page 2: the 150 mm flange OD is 285.0 mm.",
			'The PCD of the 6" SABS 1123 flange is 240.0 mm.',
			'PCD of 6" SABS flange is 240.0 mm',
			'6" PCD: 240.0 mm',
			"OD (150 mm flange): 285.0 mm",
			'Nominal size: 150 mm (6")\nFlange OD: 285.0 mm',
			"The OD is 285.0 mm for the 150 mm size.",
			'For a flange of 150 mm (6"), the OD is 285.0 mm.',
			"| Size | OD | PCD |\n| 150 mm | 285.0 | 240.0 |",
			"This is the 1600/3 row.\nBolt hole diameter (d1): 22.0 mm",
			"- 1600 kPa: 8 bolts, M20",
			'The sheet does not give a mass for the 6" 1600/3 flange.',
			'**150 mm (6") · SABS 1123 1600/3**\n\n- Flange OD: 285.0 mm\n- PCD (bolt circle diameter): '
			"240.0 mm\n- Number of bolt holes: 8\n- Bolt hole diameter (d1): 22.0 mm\n- Bolt size: M20",
		):
			with self.subTest(answer=answer):
				used, missing = reference.verify(answer, [self.ROW], [self.ROW])
				self.assertEqual((used, missing), ([self.ROW], []))

	def test_a_number_that_is_both_is_data(self):
		# the line-size row's label and its cells hold the same two figures
		used, _ = reference.verify('A 2 1/2" line is 65 mm.', [ROWS[6]], [])
		self.assertEqual(used, [ROWS[6]])

	def test_a_page_number_or_a_column_digit_needs_its_word(self):
		self.assertIsNotNone(reference.verify("See page 2.", [self.ROW], [self.ROW])[0])
		self.assertIsNone(reference.verify("Use 2 gaskets.", [self.ROW], [self.ROW])[0])
		self.assertIsNone(reference.verify("Use 1 gasket.", [self.ROW], [self.ROW])[0])

	def test_a_column_whose_name_ends_in_a_figure(self):
		rating = {
			**ROWS[7],
			"label": "PN16",
			"cells": [
				{"label": "Body test @ 1.5", "value": "2.4 MPa", "status": "ok"},
				{"label": "Seat test @ 1.1", "value": "1.76 MPa", "status": "ok"},
			],
		}
		self.assertIsNotNone(reference.verify("PN16: body test @ 1.5 is 2.4 MPa.", [rating], [])[0])
		self.assertIsNone(reference.verify("PN16: body test @ 1.5 is 1.1 MPa.", [rating], [])[0])
		self.assertIsNone(reference.verify("The seat test @ 1.1 is 16 MPa.", [rating], [])[0])

	def test_one_as_a_pronoun_is_not_a_count(self):
		# the "(d1)" of a column's name used to vouch for it by accident
		answer = 'Which one do you need? The 6" 1600/3 flange has 8 holes.'
		self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		self.assertEqual(reference.numbers("this one, or one of the others"), [])
		self.assertEqual(reference.numbers("one bolt"), [{"1"}])
		self.assertIsNone(reference.verify("It takes one bolt.", [self.ROW], [self.ROW])[0])
		for answer in ("Only one matches: OD 285.0 mm.", "Only one row matches: OD 285.0 mm."):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])

	def test_one_before_the_thing_counted_is_a_count_whatever_precedes_it(self):
		"""Review of PR #400: "the one" was read as a pronoun whatever followed."""
		for answer in ("It has only the one bolt hole.", "It takes the one bolt."):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		self.assertEqual(reference.numbers("the one bolt hole"), [{"1"}])

	def test_a_lists_own_numbering_is_not_a_figure(self):
		for answer in (
			"1. The OD is 285.0 mm.",
			"1. OD: 285.0 mm\n2. PCD: 240.0 mm\n3. Bolt holes: 8",
			'1. 150 mm (6") SABS 1123 1600/3\n2) Flange OD: 285.0 mm',
			"- 1) OD 285.0 mm",
		):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		self.assertEqual(reference.numbers("1. The OD\n2. The PCD"), [])
		# not numbering: a figure that ends its line, or a decimal
		self.assertEqual(reference.numbers("Bolt holes:\n8."), [{"8"}])
		self.assertEqual(reference.numbers("285.0 mm"), [{"285"}])
		self.assertIsNone(reference.verify("1. The OD is 150 mm.", [self.ROW], [self.ROW])[0])

	def test_a_page_reference_with_a_full_stop_keeps_its_page(self):
		"""Review of PR #400: the claim split at "p. " and left the 2 on its own."""
		for answer in ("The OD is 285.0 mm (p. 2).", "See pg. 2: OD 285.0 mm", "OD 285.0 mm. See P. 2."):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		self.assertIsNone(reference.verify("The OD is 150 mm (p. 2).", [self.ROW], [self.ROW])[0])
		self.assertIsNone(reference.verify("The OD is 285.0 mm (p. 7).", [self.ROW], [self.ROW])[0])

	def test_a_size_restated_after_a_column_is_still_the_rows(self):
		"""Review of PR #400: correct answers the first cut of this rule refused."""
		for answer in (
			"OD (150 mm): 285.0 mm",
			"PCD (150 mm): 240.0 mm",
			'Number of bolt holes (6"): 8',
			"The OD of 6 inch is 285.0 mm.",
			'The OD of 6" is 285.0 mm.',
		):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		# with no value of the column's own after it, the size is the claimed value
		for answer in ("OD (150 mm).", "The OD of 150 mm is correct.", "Flange OD (150 mm)"):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])

	def test_any_verb_or_symbol_between_column_and_number_reads_like_is(self):
		for answer in (
			"The OD will be 150 mm",
			"The OD should be 150 mm.",
			"The OD would be 150 mm",
			"The OD comes to 150 mm",
			"OD → 150 mm",
			"OD -> 150 mm",
			"OD = 150 mm",
			"The OD for a flange like this could be 150 mm",
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		for answer in ("The OD will be 285.0 mm.", "OD → 285.0 mm", 'The 6" OD comes to 285.0 mm'):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])

	def test_a_restated_size_does_not_let_the_same_number_pass_as_the_value(self):
		"""Final review of PR #400: the size in brackets was exempted, and the
		number after it then had ")" or a unit where its column should be."""
		for answer in (
			"OD (150 mm): 150 mm",
			'Flange OD (6"): 6 mm',
			'PCD (6"): 6 mm',
			"PCD [150]: 150",
			'Bolt holes (6"): 6',
			"The OD of 6 inch is 6 mm",
			"The OD of 150 mm is 150 mm",
			"Number of bolt holes of 6 inch is 6",
			# a size on the way from the column to the value does not hide the column
			"The OD of the 6 inch flange is 150 mm",
			"The OD for the 150 mm flange is 150 mm",
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		for answer in ("The OD of the 6 inch flange is 285.0 mm", "The OD for the 150 mm flange is 285.0 mm"):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])

	def test_a_column_out_of_sight_of_its_number_fails_closed(self):
		"""The look-behind is bounded; what it cannot see is not taken for a name."""
		long_winded = (
			"The OD of the flange you asked about, going by the drilling table for this nominal size "
			"and this pressure class as the sheet lists them under the SABS standard for flanges, is "
		)
		self.assertGreater(len(long_winded), 160)
		for answer in (long_winded + "150 mm", "OD:" + " " * 200 + "150 mm", "OD" + "\t" * 400 + "150"):
			with self.subTest(answer=answer[:40]):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		self.assertEqual(reference.verify(long_winded + "285.0 mm", [self.ROW], [self.ROW])[0], [self.ROW])

	def test_a_column_of_any_prompt_row_makes_the_number_a_value(self):
		"""``The OD is 150 mm`` was refused against the drilling rows and accepted
		once the prompt also held the 150 mm bolt-set row: that row has no OD, so
		the 150 "named" it."""
		bolt_set_row = ROWS[5]
		self.assertNotIn("Flange OD", [cell["label"] for cell in bolt_set_row["cells"]])
		for answer in (
			"The OD is 150 mm",
			"The flange OD is 150 mm.",
			"The PCD is 150 mm.",
			"OD (150 mm): 150 mm",
		):
			for rows, cited in (
				([ROWS[0], ROWS[1]], [ROWS[0]]),
				(ROWS, [ROWS[0]]),
				(ROWS, []),
				([ROWS[0], bolt_set_row], [bolt_set_row]),
			):
				with self.subTest(answer=answer, rows=len(rows), cited=bool(cited)):
					self.assertIsNone(reference.verify(answer, rows, cited)[0])
		# each row still answers for itself with the other in the prompt
		self.assertEqual(reference.verify("- 1600/3 drilling: OD 285.0 mm", ROWS, [])[0], [ROWS[0]])
		self.assertEqual(reference.verify("- 1600 kPa bolt set: 8 Off M20 x 75", ROWS, [])[0], [bolt_set_row])

	def test_a_number_at_the_start_of_a_line_is_numbering_only_in_a_list(self):
		"""Final review of PR #400: any line-start number was taken for numbering."""
		for answer in (
			"Number of bolt holes:\n12. Bolt size M20",
			"Bolt holes\n16) M20",
			"Number of bolt holes:\n1. Bolt size M20",
			"Flange OD:\n3. M20 bolts",
			"2. The OD is 285.0 mm.",
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		self.assertEqual(reference.numbers("Number of bolt holes:\n12. Bolt size M20"), [{"12"}, {"20"}])
		for answer in (
			"Here it is.\n1. OD 285.0 mm",
			"The values are:\n1. OD 285.0 mm\n2. PCD 240.0 mm",
			"1. OD 285.0 mm\n\n2. PCD 240.0 mm\n\n3. Bolt holes: 8",
		):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		# trimming keeps the numbering it was given
		answer = "1. 1600 kPa: PCD 240.0 mm\n2. 1000 kPa: PCD 240.0 mm"
		self.assertEqual(reference.trim_comparisons(answer, ROWS), answer)

	def test_a_column_on_its_own_line_is_finished_by_the_line_under_it(self):
		for answer in (
			"Flange OD:\n150 mm",
			"**PCD**\n\n150 mm",
			"Number of bolt holes:\n6",
			"Flange OD\n- 150 mm",
			"Bolt hole diameter (d1):\n6 mm",
		):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		for answer in (
			"Flange OD:\n285.0 mm",
			"**PCD**\n\n240.0 mm",
			'150 mm (6") SABS 1123 1600/3\nNumber of bolt holes:\n8',
			"The flange drilling for this size:\nOD 285.0 mm",
			"Bolt hole diameter (d1):\n22.0 mm",
		):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [self.ROW], [self.ROW])[0], [self.ROW])
		# a column's name with its value on the same line is a claim, not a heading
		self.assertIsNone(reference.verify("Bolt hole diameter (d1): 1 mm", [self.ROW], [self.ROW])[0])
		self.assertIsNone(reference.verify("Bolt hole diameter (d1): 6", [self.ROW], [self.ROW])[0])

	def test_a_size_before_a_columns_name_and_its_value_names_the_row(self):
		bolt_set_row = ROWS[5]
		for answer in (
			"150 mm bolt set: 8 Off M20 x 75",
			'The 6" bolt set is 8 Off M20 x 75.',
			"1600 kPa bolt size: M20",
		):
			with self.subTest(answer=answer):
				self.assertEqual(reference.verify(answer, [bolt_set_row], [bolt_set_row])[0], [bolt_set_row])
		for answer in ("It is a 150 mm bolt set.", "A 150 mm bolt length."):
			with self.subTest(answer=answer):
				self.assertIsNone(reference.verify(answer, [bolt_set_row], [bolt_set_row])[0])

	def test_an_abbreviations_stop_does_not_end_the_claim(self):
		row = {
			**ROWS[7],
			"label": "Trim 5",
			"cells": [{"label": "API trim no.", "value": "8", "status": "ok"}],
		}
		self.assertEqual(reference.verify("The API trim no. is 8.", [row], [row])[0], [row])
		self.assertIsNone(reference.verify("The API trim no. is 5.", [row], [row])[0])

	def test_known_limits(self):
		"""What the rule does NOT catch -- pinned so a change here is a decision.

		It reads wording, not meaning. A column called by another name is not
		recognised as that column, and a figure that is another cell of the same
		row is data whichever column the answer puts it under.
		"""
		for answer in (
			"The flange is 150 mm thick.",  # a synonym: no column is named "thick"
			"It weighs 150 kg.",  # likewise
			"The PCD is 285.0 mm.",  # the OD's value given as the PCD: both are cells
			"It has 22 bolt holes.",  # the hole diameter given as the count
		):
			with self.subTest(answer=answer):
				self.assertIsNotNone(reference.verify(answer, [self.ROW], [self.ROW])[0])
		# a column no row in the prompt has is not known to be a column at all
		self.assertIsNotNone(reference.verify("The OD is 150 mm.", [ROWS[5]], [ROWS[5]])[0])
		# another prompt row's cell: the claim is read as that row's, and cites it
		self.assertEqual(reference.verify("The PCD is 190.5 mm.", ROWS, [ROWS[0]])[0], [ROWS[2]])

	def test_a_long_single_line_answer_is_checked_in_linear_time(self):
		"""Review of PR #400: the look-behind patterns were searched from the start
		of the claim for every figure. A looping model's 14 kB one-line reply
		took 3.9 s in the web worker; 56 kB took over a minute."""
		import time

		for unit in ("6 bolt ", "the od is 150 mm and ", "one ", "p. 2 ", "od ( 150 mm ) : "):
			answer = unit * (14_000 // len(unit))
			started = time.perf_counter()
			reference.verify(answer, ROWS, [self.ROW])
			reference.trim_comparisons(answer, ROWS)
			self.assertLess(time.perf_counter() - started, 2.0, unit)

	def test_stripping_row_ids_is_linear_too(self):
		"""It runs on the raw reply, before the check: a run of spaces or commas
		was rescanned from every position in it (10 s at 60 kB)."""
		import time

		for answer in (
			"OD" + " " * 60_000 + "150",
			"OD" + "," * 60_000 + "150",
			"(" + "R1 " * 20_000,
			"see " * 15_000,
			"OD (see R1)" + " " * 30_000 + ".",
		):
			started = time.perf_counter()
			reference.strip_row_ids(answer)
			self.assertLess(time.perf_counter() - started, 2.0, answer[:12])
		self.assertEqual(reference.strip_row_ids("PCD is 190.5 mm   (see R3) ."), "PCD is 190.5 mm.")
		self.assertEqual(
			reference.strip_row_ids("OD 285.0 mm ,  PCD 240.0 mm ;"), "OD 285.0 mm, PCD 240.0 mm"
		)


class TrimComparisonsTest(UnitTestCase):
	def test_a_claim_naming_two_rows_and_no_value_is_dropped(self):
		answer = (
			"- 1600 kPa: PCD 240.0 mm\n- 1000 kPa: PCD 240.0 mm\n\n"
			"The 1600/3 flange and the 1000/3 flange share a PCD."
		)
		trimmed = reference.trim_comparisons(answer, ROWS)
		self.assertEqual(trimmed, "- 1600 kPa: PCD 240.0 mm\n- 1000 kPa: PCD 240.0 mm")
		self.assertEqual(reference.verify(trimmed, ROWS)[1], [])

	def test_a_claim_with_a_value_is_kept_for_the_check(self):
		answer = "The 1600/3 flange has M16 bolts like the 1000/3 one."
		self.assertEqual(reference.trim_comparisons(answer, ROWS), answer)
		self.assertIsNone(reference.verify(answer, ROWS)[0])


class PromptTest(UnitTestCase):
	def test_a_questioned_value_never_reaches_the_prompt(self):
		block = reference.reference_block([ROWS[4]], "MBP")
		self.assertNotIn("36.0", block)
		self.assertIn(f"Bolt hole diameter (d1): {reference.AWAITING}", block)
		self.assertIn("[R1] Flange Drilling Tables, page 2", block)

	def test_row_ids_are_resolved_and_unknown_ones_dropped(self):
		rows = ROWS[:3]
		self.assertEqual(reference.resolve_cited(["R2", "[r1]", "R9", "R2"], rows), [rows[1], rows[0]])

	def test_row_ids_are_stripped_from_the_answer_but_uns_numbers_are_not(self):
		self.assertEqual(reference.strip_row_ids("PCD is 190.5 mm (see R3)."), "PCD is 190.5 mm.")
		self.assertEqual(reference.strip_row_ids("PCD is 190.5 mm (from R3)."), "PCD is 190.5 mm.")
		self.assertEqual(reference.strip_row_ids("PCD is 190.5 mm, per R3."), "PCD is 190.5 mm.")
		self.assertEqual(reference.strip_row_ids("Stellite is UNS R30006."), "Stellite is UNS R30006.")


# Rows whose label spells out a value the sheet questions: the MBP pack writes
# the line size into its label, and names a questioned standard in a flange's.
LINE_QUESTIONED = {
	"name": "line-1/4",
	"sheet_title": "Line Sizes",
	"page": 1,
	"section": "Line sizes",
	"label": '1/4" = 6 mm',
	"search": '1/4" 6 mm line size nominal bore inch to mm',
	"cells": [
		{"label": "Inches", "value": '1/4"', "status": "ok"},
		{"label": "Millimetres", "value": "6", "unit": "mm", "status": reference.QUESTIONED},
	],
}
LINE_5 = {
	"name": "line-5",
	"sheet_title": "Line Sizes",
	"page": 1,
	"section": "Line sizes",
	"label": '5" = 125 mm',
	"search": '5" 125 mm line size inch to mm',
	"cells": [
		{"label": "Inches", "value": '5"', "status": "ok"},
		{"label": "Millimetres", "value": "125", "unit": "mm", "status": "ok"},
	],
}
STANDARD_QUESTIONED = {
	**drilling(700, 28, "ASME B16.5", "Class 150", "ASME ANSI class 150", pcd="863.6"),
	"cells": [
		{"label": "Standard", "value": "ASME B16.5", "status": reference.QUESTIONED},
		{"label": "PCD (bolt circle diameter)", "value": "863.6", "unit": "mm", "status": "ok"},
	],
}
# every bolt figure questioned: the 12 of the label is the flange size, and
# the same 12 is the bolt count engineering has not confirmed
BOLTS_QUESTIONED = {
	**bolt_set(300, 12, "BS 10 Table F", "12 Off M20 x 100", "BS 10 BS10 Table F"),
	"cells": [
		{"label": "Bolt set", "value": "12 Off M20 x 100", "status": reference.QUESTIONED},
		{"label": "Number of bolts", "value": "12", "status": reference.QUESTIONED},
		{"label": "Bolt size", "value": "M20", "status": reference.QUESTIONED},
	],
}


class QuestionedLabelTest(UnitTestCase):
	"""Audit M-20: a questioned value written into the row's label still reached
	the prompt, the fallback answer and the number check."""

	def test_the_prompt_and_the_fallback_do_not_carry_it(self):
		block = reference.reference_block([LINE_QUESTIONED])
		self.assertNotIn("6 mm", block)
		self.assertIn(f'1/4" = ({reference.AWAITING})', block)
		self.assertNotIn("6 mm", reference.fallback_answer([LINE_QUESTIONED]))
		self.assertEqual(reference.public_label(LINE_QUESTIONED), f'1/4" = ({reference.AWAITING})')

		block = reference.reference_block([STANDARD_QUESTIONED])
		self.assertNotIn("B16.5", block)
		self.assertIn('700 mm (28")', block)
		self.assertIn("PCD (bolt circle diameter): 863.6 mm", block)

	def test_a_label_figure_that_is_not_questioned_is_left(self):
		self.assertEqual(reference.public_label(ROWS[4]), ROWS[4]["label"])
		# the label's 12 is the size: a bare number is not cut from a label
		self.assertEqual(reference.public_label(BOLTS_QUESTIONED), BOLTS_QUESTIONED["label"])
		self.assertEqual(
			reference.describe(ROWS[0]),
			f"Flange Drilling Tables, page 2 — Flange drilling: {ROWS[0]['label']}",
		)

	def test_a_label_never_supports_a_questioned_figure(self):
		for answer, rows, cited in (
			('A 1/4" line is 6 mm.', [LINE_QUESTIONED, LINE_5], []),
			('A 1/4" line is 6 mm.', [LINE_QUESTIONED, LINE_5], [LINE_5]),
			('The 28" flange is to ASME B16.5.', [STANDARD_QUESTIONED], []),
			('The 12" BS 10 Table F flange takes 12 bolts.', [BOLTS_QUESTIONED], []),
		):
			with self.subTest(answer=answer, cited=bool(cited)):
				used, missing = reference.verify(answer, rows, cited)
				self.assertIsNone(used, missing)

	def test_the_confirmed_figures_of_such_a_row_still_pass(self):
		used, missing = reference.verify(
			'The 28" Class 150 flange has a PCD of 863.6 mm.', [STANDARD_QUESTIONED], []
		)
		self.assertEqual((used, missing), ([STANDARD_QUESTIONED], []))
		used, missing = reference.verify('A 5" line is 125 mm.', [LINE_QUESTIONED, LINE_5], [])
		self.assertEqual((used, missing), ([LINE_5], []))


class OutputTest(UnitTestCase):
	def test_the_fallback_is_the_row_with_questioned_values_withheld(self):
		text = reference.fallback_answer([ROWS[4]])
		self.assertTrue(text.startswith("Here is what the sheet says:"))
		self.assertIn("PCD (bolt circle diameter): 585.0 mm", text)
		self.assertNotIn("36.0", text)

	def test_public_cells_withhold_questioned_values(self):
		cell = ROWS[4]["cells"][1]
		self.assertEqual(reference.public_cell(cell)["value"], "")
		self.assertEqual(reference.public_cell({**cell, "note": "should it be 26.0?"})["note"], "")
		self.assertEqual(reference.public_cell(ROWS[4]["cells"][0])["value"], "585.0")

	def test_highlight_marks_the_quoted_cells_or_all(self):
		self.assertEqual(reference.highlight("PCD 240.0 mm", ROWS[0]), [1])
		self.assertEqual(reference.highlight("see the sheet", ROWS[0]), [0, 1, 2, 3])
