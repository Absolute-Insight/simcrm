# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Whitelisted entry points for agent features.

Returns a status rather than raising when the model is off or unreachable: an
unavailable endpoint should look like a feature that is not there, not like a bug.
Mirrors the shape of ``crm.domain_enrichment.api``, including its rule that every entry
point which triggers an outbound fetch is rate-limited -- here per user *and* per IP.
"""

from __future__ import annotations

import html
import time
from contextlib import contextmanager

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import strip_html_tags

from crm.agent import actions, client, knowledge, tools
from crm.agent.config import get_config, get_signal_config
from crm.agent.context import build_thread_messages
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import AssistantAnswer, ConnectionProbe, ThreadSummary
from crm.help import load_articles
from crm.utils import sales_user_only, user_rate_limited

# Per-minute cap, matching ``domain_enrichment.api.ENRICH_RATE_LIMIT``. One call
# holds a worker for up to ``timeout`` x ``client.MAX_ATTEMPTS`` -- 60 seconds at the
# shipped defaults -- so without a cap a single authenticated user can occupy the
# whole worker pool from a loop. 10/min is far above any real human burst.
#
# Applied twice, on purpose. ``@rate_limit`` is frappe's limiter and it keys on the
# *request IP* (``ip_based=True`` is its default), so on its own it is one bucket
# for a whole office behind a NAT and a fresh bucket for every address one account
# can borrow. ``user_rate_limited`` keys on the session user and is the layer that
# bounds what a single account can do; the IP layer stays as the backstop for
# unauthenticated-looking floods. Both read the same number.
SUMMARISE_RATE_LIMIT = 10
USER_RATE_SCOPE = "crm_agent_model_call"

# Tighter than the feature endpoints: this is an admin pressing a button, not a
# rep working, and each press costs a full model call against someone's endpoint.
TEST_CONNECTION_RATE_LIMIT = 6
TEST_CONNECTION_RATE_SCOPE = "crm_agent_test_connection"

# The per-user share of the day: a floor of 10 so a small budget still leaves a
# rep a working session, else a fifth of the site's budget, so no single account
# can spend more than that before everyone else is locked out for the day. It is
# derived rather than a settings field: an admin who sets the site budget has
# already said how much the endpoint may cost, and this only keeps one user from
# being the one who spends it.
USER_DAILY_BUDGET_FLOOR = 10
USER_DAILY_BUDGET_SHARE = 5

# The longest question the assistant accepts. Anything past this is a paste,
# not a question, and a paste belongs in the record it came from.
ASSISTANT_QUESTION_MAX_CHARS = 2000

BUDGET_CACHE_KEY = "crm_agent_daily_calls"


def budget_key() -> str:
	"""Today's counter key, site-scoped.

	``incr`` and ``expire`` are raw redis commands and skip the site prefix that
	``get_value``/``set_value`` apply, so the site name goes in the key by hand or
	every site on the bench spends one shared budget.
	"""
	return f"{BUDGET_CACHE_KEY}:{frappe.local.site}:{frappe.utils.today()}"


def user_budget_key(user: str | None = None) -> str:
	"""Today's per-user counter key, site-scoped like :func:`budget_key`."""
	return f"{budget_key()}:{user or frappe.session.user}"


def user_daily_call_budget(cfg) -> int:
	"""One account's share of ``daily_call_budget``; 0 (uncapped) when the site is."""
	if cfg.daily_call_budget <= 0:
		return 0
	return max(USER_DAILY_BUDGET_FLOOR, cfg.daily_call_budget // USER_DAILY_BUDGET_SHARE)


def _budget_spent(cfg) -> bool:
	"""Count this call against the daily budgets; True when either is gone.

	The per-user rate limit bounds a burst, not a day: fifty users at ten calls a
	minute is still an unbounded bill against whoever hosts the endpoint. The
	site-wide counter is a redis key per day, so it costs one incr and expires
	itself. A second counter per user keeps one account from spending the whole
	site's day on its own -- see :func:`user_daily_call_budget`.

	The user counter is charged first and a refusal is refunded: the site
	counter used to be charged before the per-user check with no refund, so one
	capped account's retries -- still permitted by the burst limiter -- kept
	incrementing the site's day on calls that never reached the model, locking
	everyone else out. A refused call must cost nobody anything.
	"""
	if cfg.daily_call_budget <= 0:
		return False
	try:
		cache = frappe.cache()
		user_key = user_budget_key()
		user_spent = cache.incr(user_key)
		cache.expire(user_key, 60 * 60 * 36)
		if user_spent > user_daily_call_budget(cfg):
			cache.decr(user_key)
			return True
		key = budget_key()
		spent = cache.incr(key)
		cache.expire(key, 60 * 60 * 36)
		if spent > cfg.daily_call_budget:
			cache.decr(key)
			cache.decr(user_key)
			return True
	except Exception:
		# a cache that is unavailable must not take the feature down with it
		return False
	return False


def _refund_budget(cfg) -> None:
	"""Give back the day-units :func:`_budget_spent` charged for a call that
	was never made -- the slot said no after the budgets said yes. Without
	this, a slow-model incident (exactly when the slots fill) burned the
	site's day on refused retries and kept the tier dark after the model
	recovered."""
	if cfg.daily_call_budget <= 0:
		return
	try:
		cache = frappe.cache()
		cache.decr(user_budget_key())
		cache.decr(budget_key())
	except Exception:
		pass


# Bounds *simultaneous* model calls per site, where the rate limits bound calls
# per minute: one call holds a web worker for up to timeout x client.MAX_ATTEMPTS,
# so ten users each inside their burst limit can still occupy the whole gunicorn
# pool at once. Four is half the shipped pool of eight (deploy compose), so the
# site keeps answering while the model is slow. test_connection stays outside
# the slots on purpose: it is System Manager only, 6/min, and its whole job is
# probing the endpoint while the tier misbehaves.
MAX_CONCURRENT_MODEL_CALLS = 4
INFLIGHT_CACHE_KEY = "crm_agent_inflight"
# TTL backstop: a worker killed between the incr and the finally leaks its slot;
# the key expiring puts the count right again within this window.
INFLIGHT_TTL_SECONDS = 600


def _inflight_key() -> str:
	"""Site-scoped like :func:`budget_key`, and for the same reason."""
	return f"{INFLIGHT_CACHE_KEY}:{frappe.local.site}"


@contextmanager
def _model_call_slot():
	"""Hold one of the site's model-call slots; yields False when all are taken."""
	try:
		cache = frappe.cache()
		taken = cache.incr(_inflight_key())
	except Exception:
		# same rule as the budgets: a cache outage must not take the tier down
		yield True
		return
	try:
		if taken == 1:
			# Armed once, at key creation: a slot leaked by a hard-killed worker
			# then always clears within the window. Re-arming on every call kept
			# a leaked slot alive for as long as traffic never paused this long.
			try:
				cache.expire(_inflight_key(), INFLIGHT_TTL_SECONDS)
			except Exception:
				pass
		yield taken <= MAX_CONCURRENT_MODEL_CALLS
	finally:
		try:
			if cache.decr(_inflight_key()) < 0:
				# the key expired under a live call; a negative floor would make
				# the limit more generous forever
				cache.delete(_inflight_key())
		except Exception:
			pass


def _throttled(cfg) -> bool:
	"""The per-user minute window, then the daily budgets -- in that order, so a
	call the burst limiter refuses is not also charged to the day."""
	return user_rate_limited(USER_RATE_SCOPE, SUMMARISE_RATE_LIMIT) or _budget_spent(cfg)


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def summarise_thread(reference_doctype: str, reference_name: str) -> dict:
	"""Summarise a record's communication thread.

	Returns ``{"status": "ok", "summary": {...}}`` on success, or a bare status of
	``disabled`` or ``unavailable``.
	"""
	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}
	if _throttled(cfg):
		return {"status": "unavailable"}

	record = tools.read_record(reference_doctype, reference_name)
	thread = tools.read_thread(reference_doctype, reference_name)
	messages = build_thread_messages(record, thread)

	with _model_call_slot() as free:
		if not free:
			# refused after the budgets were charged: a refused call costs nobody anything
			_refund_budget(cfg)
			return {"status": "unavailable"}
		try:
			summary = client.complete(cfg, ThreadSummary, messages)
		except (AgentUnavailable, SchemaMismatch) as exc:
			frappe.log_error(title="CRM agent summary failed", message=str(exc))
			return {"status": "unavailable"}

	return {"status": "ok", "summary": summary.model_dump()}


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def draft_reply(reference_doctype: str, reference_name: str) -> dict:
	"""Draft a reply to the latest inbound message on a record's thread.

	Returns ``{"status": "ok", "draft": {"subject", "body"}}`` or a bare degrade
	status. The draft is attacker-influenced text: the caller shows it in a
	compose window for a human to edit and send — it is never sent directly.
	"""
	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}
	if _throttled(cfg):
		return {"status": "unavailable"}

	record = tools.read_record(reference_doctype, reference_name)
	thread = tools.read_thread(reference_doctype, reference_name)

	with _model_call_slot() as free:
		if not free:
			# refused after the budgets were charged: a refused call costs nobody anything
			_refund_budget(cfg)
			return {"status": "unavailable"}
		try:
			draft = actions.propose_reply(cfg, record, thread)
		except (AgentUnavailable, SchemaMismatch) as exc:
			frappe.log_error(title="CRM agent reply draft failed", message=str(exc))
			return {"status": "unavailable"}

	return {"status": "ok", "draft": draft.model_dump()}


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def ask_mentor(question: str, history: str | list | None = None) -> dict:
	"""Answer a question about the product, grounded on the help articles.

	Returns ``{"status": "ok", "answer": str, "related_articles": [...]}`` or a
	bare degrade status. The Mentor reads no CRM records at all: its whole
	knowledge is the shipped manual, so there is nothing here for a hostile
	record or email to inject through, and nothing the answer can leak that the
	help center does not already show every user.
	"""
	question = _clean_question(question)

	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}
	if _throttled(cfg):
		return {"status": "unavailable"}

	articles = load_articles()
	selected = knowledge.select_articles(question, articles)
	messages = knowledge.build_assistant_messages(question, selected, _parse_history(history))

	reply = _complete_chat(cfg, messages, "CRM mentor answer failed")
	if reply is None:
		return {"status": "unavailable"}

	# The model cites articles by name; only names that actually exist survive,
	# so an invented citation cannot become a dead link in the help center.
	known = {article["name"] for article in articles}
	related = [name for name in reply.related_articles if name in known]
	return {"status": "ok", "answer": reply.answer, "related_articles": related}


# How many knowledge rows the Assistant considers. Selection is a scan over
# titles, tags and bodies, so a catalogue past this is a search index's job,
# not a prompt's.
KNOWLEDGE_ROW_LIMIT = 500


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def ask_assistant(question: str, history: str | list | None = None) -> dict:
	"""Answer a rep's question about the company's offering from the knowledge base.

	Returns ``{"status": "ok", "answer": str, "sources": [{"name", "title"}]}``,
	``{"status": "empty"}`` when nothing has been curated yet, or a bare degrade
	status. The knowledge base is administrator-authored, so it carries the same
	trust as the help articles; the product catalogue joins it only when the
	admin says so. Both are read with permission-checked ``get_list`` under the
	asking user. Nothing here reads deals, leads or email.
	"""
	question = _clean_question(question)

	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}

	articles = _knowledge_articles(cfg)
	if not articles:
		return {"status": "empty"}

	if _throttled(cfg):
		return {"status": "unavailable"}

	selected = knowledge.select_articles(question, articles)
	company = frappe.db.get_single_value("FCRM Settings", "brand_name") or "the company"
	messages = knowledge.build_assistant_messages(
		question,
		selected,
		_parse_history(history),
		system_prompt=knowledge.ASSISTANT_SYSTEM_PROMPT.format(company=company),
		no_match_note=knowledge.ASSISTANT_NO_MATCH_NOTE,
		heading="Knowledge base",
	)

	reply = _complete_chat(cfg, messages, "CRM assistant answer failed")
	if reply is None:
		return {"status": "unavailable"}

	titles = {article["name"]: article["title"] for article in articles}
	sources = [{"name": name, "title": titles[name]} for name in reply.related_articles if name in titles]
	return {"status": "ok", "answer": reply.answer, "sources": sources}


def _knowledge_articles(cfg) -> list[dict]:
	"""Every row the Assistant may quote, in the article shape the scorer reads."""
	rows = frappe.get_list(
		"CRM Knowledge Article",
		filters={"available_to_assistant": 1},
		fields=["name", "title", "tags", "body"],
		order_by="modified desc",
		limit=KNOWLEDGE_ROW_LIMIT,
	)
	articles = [
		{"name": row.name, "title": row.title, "tags": row.tags or "", "content": row.body or ""}
		for row in rows
	]
	if cfg.assistant_reads_products:
		currency = frappe.db.get_single_value("FCRM Settings", "currency") or ""
		products = frappe.get_list(
			"CRM Product",
			filters={"disabled": 0},
			fields=["name", "product_code", "product_name", "description", "standard_rate"],
			order_by="product_name asc",
			limit=KNOWLEDGE_ROW_LIMIT,
		)
		for row in products:
			row = dict(row)
			row["description"] = html.unescape(strip_html_tags(row.get("description") or ""))
			articles.append(knowledge.article_from_product(row, currency))
	return articles


def _clean_question(question: str) -> str:
	question = (question or "").strip()
	if not question:
		frappe.throw(frappe._("Ask a question."), frappe.ValidationError)
	return question[:ASSISTANT_QUESTION_MAX_CHARS]


def _complete_chat(cfg, messages: list[dict], log_title: str) -> AssistantAnswer | None:
	"""One guarded model call for the chat tiers; ``None`` means degrade."""
	with _model_call_slot() as free:
		if not free:
			# refused after the budgets were charged: a refused call costs nobody anything
			_refund_budget(cfg)
			return None
		try:
			return client.complete(cfg, AssistantAnswer, messages)
		except (AgentUnavailable, SchemaMismatch) as exc:
			frappe.log_error(title=log_title, message=str(exc))
			return None


def _parse_history(history) -> list[dict]:
	"""Whatever the wire delivered into a list of turns, dropping anything odd.

	``frappe.parse_json`` handles the string form a whitelisted arg arrives in;
	knowledge then keeps only well-shaped turns, so this only has to guarantee
	"a list or nothing".
	"""
	if isinstance(history, str):
		try:
			history = frappe.parse_json(history)
		except ValueError:
			return []
	return history if isinstance(history, list) else []


@frappe.whitelist()
@rate_limit(limit=TEST_CONNECTION_RATE_LIMIT, seconds=60)
def test_connection() -> dict:
	"""Try the configured endpoint once and report exactly what happened.

	Until this existed the only way to learn that ``base_url`` was wrong was a rep
	clicking Summarise and getting a degraded dialog -- a failure that reaches a
	user before it reaches the admin who caused it.

	Runs the *real* path (:func:`client.complete` with a schema) rather than a
	bare HTTP ping, because reaching the host proves nothing about whether guided
	decoding works there, and that is the interesting failure.

	Deliberately works with ``enabled`` off, so an endpoint can be proved before
	it is switched on for reps. Reads the saved settings rather than anything the
	caller supplies: ``base_url`` is the target of a server-side POST carrying the
	API key, so accepting one over the wire would be an SSRF with credential
	replay, and the doctype's own validation is the only thing standing in front
	of it.
	"""
	frappe.only_for("System Manager", True)

	cfg = get_config()
	if user_rate_limited(TEST_CONNECTION_RATE_SCOPE, TEST_CONNECTION_RATE_LIMIT):
		return {
			"ok": False,
			"kind": "rate_limited",
			"base_url": cfg.base_url,
			"model": cfg.model,
			"message": frappe._("Too many connection tests in a minute. Try again shortly."),
		}
	started = time.monotonic()
	try:
		client.complete(
			cfg,
			ConnectionProbe,
			[{"role": "user", "content": 'Reply with exactly {"ok": true}'}],
		)
	except AgentUnavailable as exc:
		# str(exc) is "<base_url>: <requests error>" -- no headers, so no key.
		if isinstance(exc, client.EndpointRejectedKey):
			# the host answered; the fix is the api_key field, not the URL
			return {
				"ok": False,
				"kind": "unauthorised",
				"base_url": cfg.base_url,
				"model": cfg.model,
				"message": frappe._("The endpoint rejected the API key: {0}").format(exc),
			}
		return {
			"ok": False,
			"kind": "unreachable",
			"base_url": cfg.base_url,
			"model": cfg.model,
			"message": frappe._("Could not reach the endpoint: {0}").format(exc),
		}
	except SchemaMismatch as exc:
		return {
			"ok": False,
			"kind": "schema",
			"base_url": cfg.base_url,
			"model": cfg.model,
			"message": frappe._(
				"The endpoint answered but would not follow the response schema: {0}."
				" Check that {1} exists there and supports JSON schema output."
			).format(exc, cfg.model),
		}

	elapsed = time.monotonic() - started
	return {
		"ok": True,
		"kind": "ok",
		"base_url": cfg.base_url,
		"model": cfg.model,
		"latency_ms": round(elapsed * 1000),
		# A cold model can take ten times a warm one, so the number matters as
		# much as the verdict -- it is what the timeout has to clear.
		"message": frappe._("{0} answered in {1}s with a valid reply.").format(cfg.model, f"{elapsed:.1f}"),
	}


@frappe.whitelist()
def get_settings() -> dict:
	"""The settings actually in force, defaults filled in -- what the admin page must show.

	``frappe.client.get_value`` returns ``{}`` for a Single that has never been
	saved, so the settings page drew "Generate suggestions: off" and four blank
	thresholds while the signal job was in fact running happily on
	SIGNAL_DEFAULTS. Saving that screen then made the display true: every Check
	and Int the admin had never seen a value for was written as 0, which switched
	the whole suggestion engine off and collapsed all four thresholds. An admin
	configuring the model endpoint had no way to know they had just done that.

	So the page is handed the effective configuration rather than the stored rows,
	from the same dataclasses the job itself reads. ``api_key`` is not included:
	a Password field reads back masked and round-tripping it would write the mask.
	"""
	frappe.has_permission("CRM Agent Settings", "read", throw=True)

	cfg = get_config()
	signals = get_signal_config()
	return {
		"enabled": int(cfg.enabled),
		"base_url": cfg.base_url,
		"model": cfg.model,
		"timeout": cfg.timeout,
		"max_tokens": cfg.max_tokens,
		"daily_call_budget": cfg.daily_call_budget,
		"assistant_reads_products": int(cfg.assistant_reads_products),
		"analyst_enabled": int(cfg.analyst_enabled),
		"signals_enabled": int(signals.signals_enabled),
		"idle_deal_days": signals.idle_deal_days,
		"close_horizon_days": signals.close_horizon_days,
		"suggestion_ttl_days": signals.suggestion_ttl_days,
		"dismiss_cooldown_days": signals.dismiss_cooldown_days,
		"max_open_per_user": signals.max_open_per_user,
	}
