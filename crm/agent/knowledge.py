# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Grounds the chat assistant on the in-app help articles. Pure -- rows in, messages out.

The assistant answers questions about the product, and the help center is the
product's manual, so they share one source: ``crm/help/articles``. This module
selects the articles relevant to a question and builds the chat messages; the
loading (and the site) stay in the caller, which is what keeps this importable
and testable with no frappe at all -- the same property ``context`` holds.

Unlike the thread tiers there is no fence here: the articles are constants that
ship with the app, and the question comes from the authenticated operator the
assistant serves. The untrusted channel is the *output* -- a model reply is
text to display, never to execute or render as HTML, and the caller filters
``related_articles`` against the real article names rather than trusting them.
"""

from __future__ import annotations

import re
from collections import Counter

MENTOR_SYSTEM_PROMPT = (
	"You are the Mentor for Vectora, a proactive CRM. You answer questions "
	"about how to use Vectora: its screens, settings, and how its numbers are computed. "
	"Ground every answer in the product documentation provided below; when the "
	"documentation does not answer the question, say so plainly instead of guessing. "
	"Be concise and concrete: name the screen or setting the user should go to. "
	"You cannot read or change the user's CRM records, send email, or alter settings -- "
	"if asked to, say what the user can do themselves instead. "
	"Reply only with JSON matching the provided schema. `answer` is plain text, no HTML "
	"or markdown headings. `related_articles` names up to 3 of the provided articles "
	"(by their `name`) that best help with this question; leave it empty if none apply."
)

NO_MATCH_NOTE = (
	"No documentation matched this question. Say that you do not have material on it "
	"and suggest opening the help center for the full manual."
)

# The Assistant answers a rep's questions about the company's own offering from
# the knowledge base an administrator curates. Same grounding, different
# register: a rep may be reading this on a call, and a guessed rating or price
# is worse than no answer.
ASSISTANT_SYSTEM_PROMPT = (
	"You are the sales assistant for {company}'s sales reps. A rep asks you what a customer "
	"might ask them: about the company's products, models, materials, ratings, standards, and "
	"which industries and applications use what. Answer only from the knowledge base provided "
	"below. When it does not cover the question, say so plainly and suggest checking with "
	"engineering -- never guess a specification, rating, price or delivery time. "
	"Be concise and concrete; the rep may be on a call. "
	"Reply only with JSON matching the provided schema. `answer` is plain text, no HTML "
	"or markdown headings. `related_articles` names up to 3 of the provided articles "
	"(by their `name`) that the answer relied on; leave it empty if none apply."
)

ASSISTANT_NO_MATCH_NOTE = (
	"Nothing in the knowledge base matched this question. Say that the knowledge base has "
	"no material on it and suggest the rep checks with engineering."
)

# How many articles a question may pull into the prompt, and how much of each.
# Four full articles is roughly 8-10k characters -- comfortably inside the
# context of any model worth pointing the tier at, and enough that the answer
# can quote the mechanism rather than paraphrase a summary.
DEFAULT_LIMIT = 4
ARTICLE_CHAR_CAP = 4000
TRUNCATION_NOTE = " [...truncated]"

# A term matching an article's title is a far stronger signal than one buried
# in its body; a term repeated through a body should count more than a single
# mention, but not without bound or one long article swallows every query.
TITLE_WEIGHT = 3.0
CONTENT_WEIGHT = 0.2
CONTENT_HIT_CAP = 5

# How much history the prompt carries. Enough for follow-up questions to make
# sense; not so much that a long session crowds out the documentation.
HISTORY_TURN_LIMIT = 8
HISTORY_CHAR_CAP = 2000

# When a character budget is given, the share of it history may take before the
# documentation starts losing articles. Four full articles and eight full turns
# are ~32k characters between them -- more than twice a 8k-token window -- and
# without a split the newest thing in the prompt (the history) would push the
# grounding out, which is exactly backwards for a tier whose whole value is
# being grounded.
HISTORY_BUDGET_SHARE = 0.3

_WORD = re.compile(r"[a-z0-9']+")

# Function words that would otherwise dominate overlap scoring. Deliberately
# short: an aggressive list starts eating meaningful terms ("plan", "won").
_STOPWORDS = frozenset(
	"the a an and or but of to in on at for with from as is are was be been it its "
	"this that these those there here how what where when why who which do does did "
	"i my me we our you your can could should would will".split()
)


def _tokens(text: str) -> list[str]:
	return [word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS and len(word) > 1]


def score_article(question: str, article: dict) -> float:
	"""Relevance of one article to one question. Zero means unrelated."""
	question_tokens = set(_tokens(question))
	if not question_tokens:
		return 0.0
	# Tags are the words customers use for the thing; they count like the title.
	title_tokens = set(_tokens(f"{article.get('title', '')} {article.get('tags', '')}"))
	content_counts = Counter(_tokens(article.get("content", "")))
	score = 0.0
	for token in question_tokens:
		if token in title_tokens:
			score += TITLE_WEIGHT
		score += min(content_counts.get(token, 0), CONTENT_HIT_CAP) * CONTENT_WEIGHT
	return score


def select_articles(question: str, articles: list[dict], limit: int = DEFAULT_LIMIT) -> list[dict]:
	"""The articles worth quoting for this question, best first.

	Returns an empty list when nothing scores at all -- the prompt then tells
	the model to admit it, which beats grounding an answer on the closest
	irrelevant article.
	"""
	scored = [(score_article(question, article), index, article) for index, article in enumerate(articles)]
	relevant = [entry for entry in scored if entry[0] > 0]
	# Highest score first; ties keep the catalogue's own order, which is the
	# help center's display order and therefore deterministic.
	relevant.sort(key=lambda entry: (-entry[0], entry[1]))
	return [article for _score, _index, article in relevant[:limit]]


def build_assistant_messages(
	question: str,
	articles: list[dict],
	history: list[dict] | None = None,
	system_prompt: str = MENTOR_SYSTEM_PROMPT,
	no_match_note: str = NO_MATCH_NOTE,
	heading: str = "Product documentation",
	max_chars: int | None = None,
) -> list[dict]:
	"""System + prior turns + the question, with the selected articles in the system message.

	``articles`` is the *selected* set (see :func:`select_articles`) -- the
	caller chooses what the prompt may quote. ``history`` is prior chat turns as
	``{"role": "user"|"assistant", "content": str}``; anything else is dropped
	rather than trusted, and only the most recent turns are kept. The Mentor
	and the Assistant share this builder and differ only in the persona and
	the source they are handed.

	``max_chars`` is the whole prompt's character budget, derived by the caller
	from the model's context window. Only the builder knows where the
	instruction ends and the quoted material begins, so the trimming is here:
	history loses its oldest turns first, then the documentation loses its
	lowest-scoring articles, and the instruction and the question are never
	touched. Left ``None``, the prompt is built to the old fixed caps.
	"""
	turns = _usable_history(history)
	documentation_budget = None
	if max_chars is not None:
		spare = max(0, max_chars - len(system_prompt) - len(question))
		turns = _fit_history(turns, int(spare * HISTORY_BUDGET_SHARE))
		documentation_budget = spare - sum(len(turn["content"]) for turn in turns)
	documentation = _documentation_block(articles, no_match_note, heading, documentation_budget)
	messages = [{"role": "system", "content": f"{system_prompt}\n\n{documentation}"}]
	for turn in turns:
		messages.append(turn)
	messages.append({"role": "user", "content": question})
	return messages


def _fit_history(turns: list[dict], budget: int) -> list[dict]:
	"""The newest turns that fit ``budget`` characters between them."""
	kept: list[dict] = []
	for turn in reversed(turns):
		budget -= len(turn["content"])
		if budget < 0:
			break
		kept.append(turn)
	kept.reverse()
	return kept


def article_from_product(row: dict, currency: str) -> dict:
	"""A ``CRM Product`` row in the article shape the scorer and the prompt read.

	``description`` arrives as the editor's HTML; the caller strips it before
	handing the row here so this stays frappe-free. The name is prefixed so a
	product can never collide with a knowledge article's ``KB-`` name and a
	citation of it is recognisable in ``sources``.
	"""
	code = row.get("product_code") or ""
	description = (row.get("description") or "").strip()
	rate = row.get("standard_rate")
	parts = [f"Product code {code}." if code else "", description]
	if rate:
		parts.append(f"Standard rate {rate:,.2f} {currency}.")
	return {
		"name": f"product:{row.get('name', '')}",
		"title": row.get("product_name") or code or row.get("name", ""),
		"tags": code,
		"content": " ".join(part for part in parts if part).strip() or "No description.",
	}


def _documentation_block(
	articles: list[dict],
	no_match_note: str = NO_MATCH_NOTE,
	heading: str = "Product documentation",
	budget: int | None = None,
) -> str:
	"""The grounding block, best-scoring article first, inside ``budget`` characters.

	``articles`` arrives ranked, so spending the budget in order spends it on
	the articles most likely to answer the question. An article that does not
	fit whole is truncated and marked; once the budget is gone the rest are
	dropped rather than included as stubs, because a heading with no body reads
	to the model as an article that had nothing to say.
	"""
	if not articles:
		return f"# {heading}\n\n{no_match_note}"
	remaining = budget
	sections = []
	for article in articles:
		header = f"## Article `{article.get('name', '')}`: {article.get('title', '')}\n"
		cap = ARTICLE_CHAR_CAP
		if remaining is not None:
			cap = min(cap, remaining - len(header))
			if cap <= len(TRUNCATION_NOTE):
				break
		content = article.get("content", "")
		if len(content) > cap:
			content = content[: cap - len(TRUNCATION_NOTE)] + TRUNCATION_NOTE
		if remaining is not None:
			remaining -= len(header) + len(content)
		sections.append(f"{header}{content}")
	if not sections:
		return f"# {heading}\n\n{no_match_note}"
	return f"# {heading}\n\n" + "\n\n".join(sections)


def _usable_history(history: list[dict] | None) -> list[dict]:
	turns = []
	for turn in history or []:
		if not isinstance(turn, dict):
			continue
		role = turn.get("role")
		content = turn.get("content")
		if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
			continue
		turns.append({"role": role, "content": content[:HISTORY_CHAR_CAP]})
	return turns[-HISTORY_TURN_LIMIT:]
