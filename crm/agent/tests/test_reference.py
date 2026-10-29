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

	def test_a_short_row_wins_a_conversion_question(self):
		picked = reference.select_entries("what is 2 1/2 inch in mm", ROWS)
		self.assertEqual(labels(picked)[:1], ['2 1/2" = 65 mm'])

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

	def test_one_claim_may_not_mix_a_row_and_an_article(self):
		article = ["Standard stud lengths: 65, 75 and 90 mm."]
		used, _ = reference.verify("8 Off M20 x 90", [ROWS[5]], [], article)
		self.assertIsNone(used)
		used, _ = reference.verify("Studs come in 90 mm.", [ROWS[5]], [], article)
		self.assertEqual(used, [])

	def test_a_unicode_minus_keeps_its_sign(self):
		self.assertEqual(reference.numbers("\u221229 \u00baC"), [{"-29"}])
		self.assertEqual(reference.numbers("15\u201320 bar"), [{"15"}, {"20"}])


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
