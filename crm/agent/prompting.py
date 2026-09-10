# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Prompt arithmetic every builder needs and none of them owns. Pure -- no frappe.

Two jobs live here because two tiers each had half of one.

**Sizing.** A model has a context window and a prompt larger than it is not an
error the caller sees. Ollama truncates from the *head* -- which is exactly
where the system instruction and the grounding sit -- and answers ``200`` with
a reply that was never guided by either; vLLM and llama.cpp answer ``400``,
which the client used to report as "unreachable". So the size of a prompt has
to be decided before it is sent, and that needs an estimate.

Nothing here counts tokens exactly: that needs the model's own tokeniser and
the model is configuration. :data:`CHARS_PER_TOKEN` is a deliberate
*under*-estimate of characters per token for English prose (BPE averages ~4)
so a budget computed from it errs towards a prompt that fits rather than one
that is silently beheaded.

**Fencing.** Text that came out of the database is data, never instruction.
The marker substitution is here rather than in ``context`` so the thread tiers
and the Analyst share one implementation instead of two that drift.
"""

from __future__ import annotations

import math

# Characters per token. BPE on English prose runs about four; 3.5 keeps the
# estimate on the high side of the true token count, which is the safe side.
CHARS_PER_TOKEN = 3.5

# What a chat template spends per message on role framing, whatever the model.
# Small, but eight history turns' worth of it is not nothing.
MESSAGE_OVERHEAD_TOKENS = 4

# What a fence marker found inside untrusted content is replaced with.
NEUTRALISED_MARKER = "[fence marker removed]"


def estimate_tokens(text) -> int:
	"""A rough token count for ``text``. Over-estimates rather than under."""
	return math.ceil(len(str(text or "")) / CHARS_PER_TOKEN)


def estimate_messages(messages: list[dict]) -> int:
	"""The same estimate for a whole chat request, role framing included."""
	return sum(estimate_tokens(message.get("content", "")) + MESSAGE_OVERHEAD_TOKENS for message in messages)


def tokens_to_chars(tokens: int) -> int:
	"""The character budget a token budget buys, on the same rough exchange rate."""
	return max(0, int(tokens * CHARS_PER_TOKEN))


def fit_messages(messages: list[dict], budget_tokens: int) -> list[dict]:
	"""``messages`` with the oldest droppable turns removed until it fits.

	Droppable is everything that is neither the leading system message -- the
	instruction, and the grounding it carries -- nor the final turn, which is
	the question being asked. Those two *are* the request; everything between
	them is history, and history is what a fourth follow-up adds until the
	window overflows and the endpoint quietly drops the instruction instead.

	Returns the two undroppable messages even when they do not fit on their
	own. Trimming the grounding block is the builder's job, because only the
	builder knows where the instruction ends and the quoted material begins;
	if it left something too big, a prompt the endpoint refuses out loud is a
	better outcome than one it truncates in silence.
	"""
	if estimate_messages(messages) <= budget_tokens:
		return list(messages)
	head = messages[:1] if messages and messages[0].get("role") == "system" else []
	tail = list(messages[len(head) :])
	if len(tail) <= 1:
		return list(messages)
	question = tail.pop()
	while tail and estimate_messages([*head, *tail, question]) > budget_tokens:
		tail.pop(0)
	return [*head, *tail, question]


def neutralise(content, markers) -> str:
	"""Replace fence ``markers`` in quoted content so it cannot escape its own fence.

	Substituting a placeholder rather than deleting the marker is the whole
	point. A single ``str.replace`` pass that deletes leaves the surrounding
	fragments adjacent, and they can spell the marker again: ``("THRE" +
	"THREAD>>>" + "AD>>>").replace("THREAD>>>", "")`` is exactly
	``"THREAD>>>"``, a live fence terminator. The placeholder keeps the
	leftovers apart -- and makes the tampering visible to the model instead of
	hiding it.
	"""
	text = str(content or "")
	for marker in markers:
		text = text.replace(marker, NEUTRALISED_MARKER)
	return text
