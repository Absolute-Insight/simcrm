# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The shared prompt arithmetic: the token estimate, the trimmer and the neutraliser."""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.agent import prompting


class EstimateTest(UnitTestCase):
	def test_the_estimate_is_on_the_high_side_of_the_true_token_count(self):
		"""BPE on English prose runs about four characters a token; erring low on
		characters-per-token means erring high on tokens, which is the safe side."""
		prose = "The quick brown fox jumps over the lazy dog. " * 20
		self.assertGreater(prompting.estimate_tokens(prose), len(prose) / 4)

	def test_nothing_costs_nothing(self):
		self.assertEqual(prompting.estimate_tokens(""), 0)
		self.assertEqual(prompting.estimate_tokens(None), 0)

	def test_a_message_costs_its_content_plus_the_role_framing(self):
		one = [{"role": "user", "content": "hello"}]
		self.assertEqual(
			prompting.estimate_messages(one),
			prompting.estimate_tokens("hello") + prompting.MESSAGE_OVERHEAD_TOKENS,
		)

	def test_the_two_budgets_are_the_same_budget(self):
		self.assertEqual(prompting.tokens_to_chars(1000), int(1000 * prompting.CHARS_PER_TOKEN))
		self.assertEqual(prompting.tokens_to_chars(-5), 0)


class FitMessagesTest(UnitTestCase):
	def messages(self, turns: int, size: int = 1000) -> list[dict]:
		history = [
			{"role": "user" if index % 2 == 0 else "assistant", "content": f"turn{index} " + "x" * size}
			for index in range(turns)
		]
		return [
			{"role": "system", "content": "the instruction"},
			*history,
			{"role": "user", "content": "the question"},
		]

	def test_a_prompt_that_fits_is_returned_unchanged(self):
		messages = self.messages(2)
		self.assertEqual(prompting.fit_messages(messages, 100_000), messages)

	def test_the_oldest_turns_go_first(self):
		messages = self.messages(4)
		fitted = prompting.fit_messages(messages, 700)
		kept = " ".join(message["content"] for message in fitted)
		self.assertNotIn("turn0", kept)
		self.assertIn("turn3", kept)

	def test_the_instruction_and_the_question_always_survive(self):
		"""Ollama drops the *head* of an over-long prompt, which is the instruction
		and the grounding. Whatever else goes, those two are the request."""
		fitted = prompting.fit_messages(self.messages(6), 10)
		self.assertEqual(
			fitted,
			[
				{"role": "system", "content": "the instruction"},
				{"role": "user", "content": "the question"},
			],
		)

	def test_a_prompt_with_no_system_message_keeps_its_final_turn(self):
		messages = [
			{"role": "user", "content": "old " + "x" * 4000},
			{"role": "user", "content": "the question"},
		]
		self.assertEqual(prompting.fit_messages(messages, 10), messages[-1:])

	def test_the_caller_is_not_mutated(self):
		messages = self.messages(4)
		prompting.fit_messages(messages, 10)
		self.assertEqual(len(messages), 6)


class NeutraliseTest(UnitTestCase):
	MARKERS = ("<<<FIGURES", "FIGURES>>>")

	def test_a_marker_in_quoted_content_is_replaced_not_removed(self):
		"""Deleting leaves the fragments adjacent, and they can spell the marker
		again: ("FIGU" + "FIGURES>>>" + "RES>>>") with the marker deleted *is* a
		live terminator. The placeholder keeps the leftovers apart."""
		text = "FIGU" + "FIGURES>>>" + "RES>>>"
		cleaned = prompting.neutralise(text, self.MARKERS)
		self.assertNotIn("FIGURES>>>", cleaned)
		self.assertIn(prompting.NEUTRALISED_MARKER, cleaned)

	def test_both_markers_are_neutralised(self):
		cleaned = prompting.neutralise("a <<<FIGURES b FIGURES>>> c", self.MARKERS)
		self.assertEqual(cleaned.count(prompting.NEUTRALISED_MARKER), 2)

	def test_non_strings_survive_as_text(self):
		self.assertEqual(prompting.neutralise(None, self.MARKERS), "")
		self.assertEqual(prompting.neutralise(42, self.MARKERS), "42")
