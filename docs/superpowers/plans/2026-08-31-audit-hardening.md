# Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 20 verified findings from the 2026-08-31 audit of the agentic and deterministic workflow surface (agent tier, signals, automation rules, rep planning, dashboard analytics, enrichment fallback).

**Architecture:** Nine tasks, one commit each, ordered so that pure-logic fixes land with pure tests and site-touching fixes land with IntegrationTestCase tests. No behavioural change beyond the finding being fixed; every fix follows the file's own documented conventions (degrade-never-raise in the agent tier, pure detectors in signals, one-source-of-numbers in dashboard).

**Tech Stack:** Frappe 17 (pinned), Python 3.11, MariaDB, redis. Tests run via `bench run-tests` inside the `simcrm_devcontainer-frappe-1` container against the dedicated `test_site`, with `PYTHONPATH=/workspace/.worktrees/fix-audit` so the worktree — not the bench's symlinked main tree — is what runs.

**Spec:** The audit findings, reproduced per task below (this plan is self-contained; the audit ran in-session).

## Global Constraints

- Test command shape: `docker exec simcrm_devcontainer-frappe-1 bash -c 'cd /home/frappe/frappe-bench && PYTHONPATH=/workspace/.worktrees/fix-audit bench --site test_site run-tests --app crm --module <dotted.module>'` — `--module` takes ONE dotted module; never pass a package (silent false green, documented in `.pi/feats/agent/README.md`).
- After any doctype JSON change: bump its `"modified"` timestamp AND run `... bench --site test_site migrate` (same PYTHONPATH) before the tests that need the new column.
- Commit style: `fix:` / `test:` / `docs:` prefixes, one logical change per commit, from the worktree at `/home/evo/dev/simcrm/.worktrees/fix-audit`.
- The agent tier's contract: degrade, never raise. Config normalisation must not raise out of `get_config()`; endpoints return `{"status": ...}`.
- `signals.py` and `predict.py` must not import `crm.agent.client` (enforced by `test_layering.py`).
- `actions.py` must not import `frappe` (enforced by `test_actions.py`).

---

### Task 1: `get_config()` reads zero-filled Ints on env-provisioned sites

**Finding:** `crm/agent/config.py:160` — `get_cached_doc().as_dict()` zero-fills never-saved Int fields. A deploy provisioned by `install.apply_endpoint_defaults` (writes only `enabled`/`base_url`/`model`) gets `timeout=0`, `max_tokens=0` (dead client) and `daily_call_budget=0` (uncapped). `get_signal_config` already documents and avoids this exact hazard via `get_singles_dict`; `get_config` does not.

**Files:**
- Modify: `crm/agent/config.py:158-168`
- Test: `crm/agent/tests/test_settings.py` (site-touching settings tests live here)

- [ ] **Step 1: Write the failing test** — in `test_settings.py`, a test that deletes the Singles rows, writes only the three fields `apply_endpoint_defaults` writes, clears caches, and asserts `get_config()` returns the shipped defaults for the rest:

```python
class EnvProvisionedConfigTest(IntegrationTestCase):
	"""A site seeded only by apply_endpoint_defaults must run on the shipped defaults.

	as_dict() on a partially-saved Single coerces the unsaved Int fields to 0,
	which made timeout=0 (every call dead on arrival) and daily_call_budget=0
	(uncapped) on exactly the deploy path the docs describe.
	"""

	def setUp(self):
		super().setUp()
		self.saved = frappe.db.get_singles_dict("CRM Agent Settings")

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": "CRM Agent Settings"})
		for field, value in self.saved.items():
			frappe.db.set_single_value("CRM Agent Settings", field, value)
		frappe.clear_cache()
		super().tearDown()

	def test_a_site_seeded_only_by_env_defaults_gets_working_numbers(self):
		frappe.db.delete("Singles", {"doctype": "CRM Agent Settings"})
		frappe.db.set_single_value("CRM Agent Settings", "enabled", 1)
		frappe.db.set_single_value("CRM Agent Settings", "base_url", "http://model:11434/v1")
		frappe.db.set_single_value("CRM Agent Settings", "model", "test-model")
		frappe.clear_cache()

		cfg = get_config()
		self.assertTrue(cfg.enabled)
		self.assertEqual(cfg.base_url, "http://model:11434/v1")
		self.assertEqual(cfg.timeout, DEFAULT_SETTINGS["timeout"])
		self.assertEqual(cfg.max_tokens, DEFAULT_SETTINGS["max_tokens"])
		self.assertEqual(cfg.daily_call_budget, DEFAULT_SETTINGS["daily_call_budget"])
```

- [ ] **Step 2: Run it, expect FAIL** (timeout comes back 0).
- [ ] **Step 3: Implement** — read the Single the way `get_signal_config` does; keep the cached doc only for password decryption:

```python
def get_config() -> AgentConfig:
	"""Build an ``AgentConfig`` from the Settings Single.

	Read through ``get_singles_dict`` rather than the cached document for the
	same reason ``get_signal_config`` does: ``as_dict()`` coerces an Int field
	that was never saved to 0, so a site provisioned only by
	``install.apply_endpoint_defaults`` (enabled, base_url, model) ran with
	``timeout=0`` — every call's deadline already expired — and
	``daily_call_budget=0``, which reads as *uncapped*. The cached document is
	still the only way to decrypt the Password field, so it is kept for that.
	"""
	settings = frappe.db.get_singles_dict("CRM Agent Settings")
	try:
		doc = frappe.get_cached_doc("CRM Agent Settings")
		settings["api_key"] = doc.get_password("api_key", raise_exception=False) or ""
	except Exception:
		settings["api_key"] = ""
	return AgentConfig.from_settings(settings)
```

- [ ] **Step 4: Run the new test + the module's existing suites** (`crm.agent.tests.test_settings`, `crm.agent.tests.test_config`, `crm.agent.tests.test_settings_endpoint`, `crm.agent.tests.test_api`). Expect PASS.
- [ ] **Step 5: Commit** `fix: agent config read zeroes on an env-provisioned site`

---

### Task 2: budget counters charge refused calls; nothing bounds concurrent model calls

**Finding A:** `crm/agent/api.py:98` — `_budget_spent` increments the site-wide counter before the per-user check and never refunds a refusal, so one capped user's retries exhaust the site's day.
**Finding B (cleanup tier):** each model call holds a gunicorn worker up to `timeout × MAX_ATTEMPTS` (~60 s at defaults) with nothing bounding simultaneous calls.

**Files:**
- Modify: `crm/agent/api.py:84-140` (and the two other endpoints' call sites)
- Test: `crm/agent/tests/test_api.py`

- [ ] **Step 1: Write failing tests** in `test_api.py`:

```python
def test_a_capped_users_retries_do_not_burn_the_site_budget(self):
	# user share for budget 500 is 100; pin the user counter at its cap
	cache = frappe.cache()
	cache.set_value  # (use raw redis: cache.setex on the exact keys)
	user_key = api.user_budget_key()
	site_key = api.budget_key()
	cache.delete_value(site_key)
	frappe.cache().setex(user_key, 3600, 100)
	cfg = SimpleNamespace(daily_call_budget=500)
	self.assertTrue(api._budget_spent(cfg))
	# the refusal charged nothing: site counter untouched, user counter not crept
	self.assertEqual(int(frappe.cache().get(user_key) or 0), 100)
	self.assertFalse(frappe.cache().get(site_key))

def test_a_full_slot_set_reports_unavailable_and_releases(self):
	key = api._inflight_key()
	frappe.cache().setex(key, 60, api.MAX_CONCURRENT_MODEL_CALLS)
	with api._model_call_slot() as free:
		self.assertFalse(free)
	# the slot taken by the refused call was released on exit
	self.assertEqual(int(frappe.cache().get(key)), api.MAX_CONCURRENT_MODEL_CALLS)
	frappe.cache().delete_value(key)
```

- [ ] **Step 2: Run, expect FAIL** (site counter incremented; `_model_call_slot` undefined).
- [ ] **Step 3: Implement.** Reorder `_budget_spent` (user first, refund refusals, site only after the user passes, refund both on site refusal — keep the cache-down `return False` contract). Add the slot guard and wrap only the `client.complete`/`actions.propose_reply` call in the three rep-facing endpoints (`summarise_thread`, `draft_reply`, `ask_assistant`); `test_connection` stays outside it — System Manager only, 6/min, and its purpose is probing while the tier misbehaves:

```python
def _budget_spent(cfg) -> bool:
	"""Count this call against the daily budgets; True when either is gone.

	The user counter is charged first and a refusal is refunded: a capped
	user's retries used to keep incrementing the *site* counter, so one
	account's refused calls could spend everyone else's day — the exact thing
	the per-user share exists to prevent. A refused call must cost nobody
	anything.
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


# Bounds *simultaneous* calls per site, where the rate limits bound calls per
# minute: one call holds a web worker for up to timeout × client.MAX_ATTEMPTS,
# so ten users inside their burst limits can still occupy the whole gunicorn
# pool. Four is half the shipped pool of eight (deploy/docker-compose.yml), so
# the site keeps answering while the model is slow.
MAX_CONCURRENT_MODEL_CALLS = 4
INFLIGHT_CACHE_KEY = "crm_agent_inflight"
# TTL backstop: a worker killed between incr and the finally leaks its slot;
# the key expiring puts the count right again within this window.
INFLIGHT_TTL_SECONDS = 600


def _inflight_key() -> str:
	return f"{INFLIGHT_CACHE_KEY}:{frappe.local.site}"


@contextmanager
def _model_call_slot():
	"""Hold one of the site's model-call slots; yields False when all are taken."""
	try:
		cache = frappe.cache()
		taken = cache.incr(_inflight_key())
		cache.expire(_inflight_key(), INFLIGHT_TTL_SECONDS)
	except Exception:
		# same rule as the budgets: a cache outage must not take the tier down
		yield True
		return
	try:
		yield taken <= MAX_CONCURRENT_MODEL_CALLS
	finally:
		try:
			if cache.decr(_inflight_key()) < 0:
				# the key expired under a live call; a negative floor would make
				# the limit more generous forever
				cache.delete_value(_inflight_key())
		except Exception:
			pass
```

Call-site shape (same in all three endpoints — reads stay outside the slot, only the model call inside):

```python
	with _model_call_slot() as free:
		if not free:
			return {"status": "unavailable"}
		try:
			summary = client.complete(cfg, ThreadSummary, messages)
		except (AgentUnavailable, SchemaMismatch) as exc:
			frappe.log_error(title="CRM agent summary failed", message=str(exc))
			return {"status": "unavailable"}
```

- [ ] **Step 4: Run** `crm.agent.tests.test_api` + `crm.agent.tests.test_layering`. Expect PASS.
- [ ] **Step 5: Commit** `fix: refused agent calls burned the site budget; bound concurrent model calls`

---

### Task 3: every period-over-period delta is biased (previous window one day short)

**Finding:** `crm/api/dashboard.py:323-327` and seven copies + `get_plan_adherence:1899` — current window is `[from_date, to_date]` inclusive (`diff+1` days) but the previous window is `[from_date - diff, from_date)` (`diff` days).

**Files:**
- Modify: `crm/api/dashboard.py` (the 8 tiles at lines ~323, 378, 445, 513, 576, 640, 702, 773; `get_plan_adherence` ~1899)
- Test: `crm/tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test** — pure on the helper plus one integration case:

```python
def test_the_previous_window_is_the_same_length_as_the_current_one(self):
	# Aug 1..Aug 31 is 31 days; the previous window must be Jul 1..Jul 31,
	# not Jul 2..Jul 31 (which read as +3.3% growth on uniform activity)
	prev_from, to_plus_one = dashboard.period_windows("2026-08-01", "2026-08-31")
	self.assertEqual(prev_from, "2026-07-01")
	self.assertEqual(to_plus_one, "2026-09-01")
	# a single-day period compares against the single previous day
	prev_from, to_plus_one = dashboard.period_windows("2026-08-15", "2026-08-15")
	self.assertEqual(prev_from, "2026-08-14")
	self.assertEqual(to_plus_one, "2026-08-16")
```

Integration: create one lead on the first day of the previous month (the day the old arithmetic excluded), one in the current month; assert `get_total_leads` reports `delta == 0.0`.

- [ ] **Step 2: Run, expect FAIL** (`period_windows` undefined).
- [ ] **Step 3: Implement** the helper and use it at all nine sites:

```python
def period_windows(from_date, to_date) -> tuple[str, str]:
	"""``(prev_from_date, to_date_plus_one)`` for a period-over-period tile.

	The current window is ``[from_date, to_date]`` inclusive — ``diff + 1``
	days. The previous window must be the same length, ending the day before
	``from_date``: ``[prev_from_date, from_date)``. The old arithmetic used
	``diff`` days, so every tile compared a 31-day month against a 30-day
	window and reported ~3.3% growth on uniform activity.
	"""
	days = frappe.utils.date_diff(to_date, from_date) + 1
	return frappe.utils.add_days(from_date, -days), frappe.utils.add_days(to_date, 1)
```

Each tile's preamble (`diff = ...` / `if diff == 0` / `prev_from_date = ...` / `to_date_plus_one = ...`) collapses to `prev_from_date, to_date_plus_one = period_windows(from_date, to_date)` (the two avg-time tiles keep their `prev_to_date = from_date`). `get_plan_adherence`:

```python
	days = date_diff(to_date, from_date) + 1
	previous = plan_adherence(add_days(from_date, -days), add_days(from_date, -1), user)[0]
```

- [ ] **Step 4: Run** `crm.tests.test_dashboard` + `crm.tests.test_metrics`. Expect PASS (adjust any existing test that pinned the biased window on purpose — read it before changing it).
- [ ] **Step 5: Commit** `fix: every period-over-period delta compared a longer window with a shorter one`

---

### Task 4: funnel stamps territory_filtered=true while two of its three counts ignore territory

**Finding:** `crm/api/dashboard.py:1154-1155` — only the Leads count is territory-scoped; `get_deal_status_change_counts` and `lost_deal_count` take no territory at all, yet `funnel_conversion` is not in `TERRITORY_BLIND` so the response vouches it is filtered.

**Files:**
- Modify: `crm/api/dashboard.py:1154-1155, 1758-1828`
- Test: `crm/tests/test_territory_filter.py`

- [ ] **Step 1: Write the failing test:** two deals in different territories both passing through a stage; `get_funnel_conversion(territory="EMEA")` must count only the EMEA deal in the stage rows and the Lost row.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement:** add `territory: str | None = None` to both helpers, `query = apply_territory(query, CRMDeal, territory)` (funnel joins CRM Deal in both), pass `territory` from `get_funnel_conversion`.
- [ ] **Step 4: Run** `crm.tests.test_territory_filter` + `crm.tests.test_dashboard`. Expect PASS.
- [ ] **Step 5: Commit** `fix: the funnel vouched for a territory filter that only reached its lead row`

---

### Task 5: dashboard/predict consistency cleanups

Four small confirmed findings, one commit:

**Files:**
- Modify: `crm/fcrm/doctype/crm_deal/crm_deal.json` (index), `crm/agent/predict.py:279-340`, `crm/api/dashboard.py:199-223, 2443-2461`, `crm/agent/predict.py:250-259`
- Test: `crm/agent/tests/test_predict.py`, `crm/tests/test_metrics.py`

- [ ] **Step 1: `health_scored_on` index** — add `"search_index": 1` to the field in `crm_deal.json`, bump the doctype's `"modified"`, run `migrate`. Fixes the per-tile-render full-table `MAX(health_scored_on)` scan at `dashboard.py:2129`.
- [ ] **Step 2: closed-deal score cleanup** — in `score_open_deals`, the `if not scored: return 0` early return skips the closed-deal clearing below it, so when the last open deals close their scores stay forever. Restructure: run the scoring loop only when `scored`, run the closed-deal clearing unconditionally, return the count. Failing test first: score a deal, mark its status Won, empty the open set, run `score_open_deals()`, assert `health_scored_on` is cleared.
- [ ] **Step 3: inbound-ratio drift** — `get_deal_health` computes `inbound_ratio` over at most 200 fetched rows while the tile's `_inbound_ratio` counts all Communications; on a deal past 200 the page and tile disagree. Replace the fetch in `get_deal_health` with the tile's own aggregate:

```python
	from crm.api.dashboard import _inbound_ratio

	inbound_ratio = _inbound_ratio([name]).get(name)
```

(Function-level import, same direction `score_open_deals` already uses; no cycle.)
- [ ] **Step 4: `visible_reps` duplication** — it is a line-for-line copy of `crm_rep_plan.visible_users()`; drifting permission logic. Delegate:

```python
def visible_reps() -> list[str] | None:
	"""Users whose plans and targets the caller may read, or ``None`` for everyone.

	One definition, shared with the planner: this *is*
	``crm_rep_plan.visible_users`` — plan and quota aggregates are keyed on a
	user rather than a deal, so both need the same subtree, and two copies of
	the same permission logic is one silent divergence away from a manager
	reading outside their tree.
	"""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	return visible_users()
```

- [ ] **Step 5: leaf-manager forecast scope** — `forecast_accuracy_scope` hands an in-hierarchy user with no descendants a `Team` series, but `forecast_snapshot_scopes` only writes Team rows for nodes with descendants (`rgt - lft > 1`), so their chart can never populate. Route them to their own Rep series:

```python
	reps = visible_reps()
	if reps is None:
		return "Site", "", None
	if sorted(set(reps)) == [frappe.session.user]:
		# an in-hierarchy leaf: no Team snapshot is ever written for a node
		# with no descendants, so their series is their own Rep row
		return "Rep", frappe.session.user, [frappe.session.user]
	return "Team", frappe.session.user, reps
```

Failing test first in `test_metrics.py` (or wherever forecast-accuracy tests live): an in-hierarchy user with no children gets scope `Rep`.
- [ ] **Step 6: Run** `crm.agent.tests.test_predict`, `crm.tests.test_metrics`, `crm.tests.test_dashboard`, `crm.tests.test_rep_plan_api`. Expect PASS.
- [ ] **Step 7: Commit** `fix: four dashboard/scoring consistency defects from the audit`

---

### Task 6: dedupe holes and stale-plan nags in signals

**Findings:** `signals.py:461` — dedupe keys omit the user (one rep's row blocks another's forever) and candidates are not deduped against each other (duplicate inserts in one run). `signals.py:679` — `_stale_plan_rows` ignores `manual_override` and lateness has no floor, so declining an item nags the rep immediately, with a negative days-late factor.

**Files:**
- Modify: `crm/agent/signals.py:373-419, 437-468, 662-694`
- Test: `crm/agent/tests/test_signals.py`

- [ ] **Step 1: Failing pure tests:**

```python
def test_two_candidates_for_the_same_key_insert_once(self):
	# a missed Call and a missed Email on one deal are both stale_plan on D
	a = candidate(signal="stale_plan", reference_docname="D", user="rep@x.com", score=60)
	b = candidate(signal="stale_plan", reference_docname="D", user="rep@x.com", score=57)
	fresh = dedupe([a, b], existing=[], now=NOW)
	self.assertEqual(len(fresh), 1)
	self.assertEqual(fresh[0]["score"], 60)  # the higher-ranked one survives

def test_one_reps_open_row_does_not_block_another_reps_candidate(self):
	existing = [row(signal="stale_plan", reference_docname="D", user="a@x.com", status="Open")]
	fresh = dedupe([candidate(signal="stale_plan", reference_docname="D", user="b@x.com")], existing, NOW)
	self.assertEqual(len(fresh), 1)

def test_a_hand_missed_future_item_is_not_a_stale_plan_candidate(self):
	# integration: mark_missed on a Thursday item on Tuesday; _stale_plan_rows
	# must not return it (manual_override)

def test_lateness_never_goes_negative(self):
	rows = [plan_row(status="Missed", planned_date=TODAY + timedelta(days=2))]
	out = find_stale_plan_items(rows, NOW)
	self.assertEqual(out[0]["score"], PLAN_MISSED_SCORE_BASE)
	late_factor = next(f for f in out[0]["factors"] if f["key"] == "days_late")
	self.assertGreaterEqual(late_factor["value"], 0)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement:**
  - `_existing_suggestions`: add `"user"` to the selected fields.
  - `dedupe`: key becomes `(signal, reference_docname, row.get("user") or "")`; after the existing-row check, also record each emitted candidate's key in a `seen` set (candidates iterated in `_rank_key` order so the highest-ranked duplicate survives deterministically) and skip keys already seen.
  - `_stale_plan_rows`: add `.where(item.manual_override == 0)` (the same respect `_match_plan` shows at `rep_planning.py:306`).
  - `find_stale_plan_items`: `late = max(0, (today - planned).days) if planned else None`.
- [ ] **Step 4: Run** `crm.agent.tests.test_signals` + `crm.agent.tests.test_thresholds`. Expect PASS.
- [ ] **Step 5: Commit** `fix: suggestion dedupe blocked across reps and doubled within a run; declined plan items nagged`

---

### Task 7: automation rules bypass the suggestion lifecycle; the task flap guard keys on the title

**Findings:** `automation.py:203` — Create Suggestion's only duplicate check is `exists(status='Open')`: dismiss/accept cooldowns and the per-user cap never apply. `automation.py:176` — the Create Task guard keys on the rendered title: a `{{ doc.status }}` title stacks one task per flap; two rules with equal titles suppress each other.

**Files:**
- Modify: `crm/agent/signals.py` (new helper), `crm/automation.py:174-238`, `crm/fcrm/doctype/crm_task/crm_task.json` (new hidden field)
- Test: `crm/tests/test_automation.py`

- [ ] **Step 1: Failing tests:**

```python
def test_a_dismissed_rule_suggestion_is_not_recreated_inside_the_cooldown(self):
	# fire rule -> dismiss the suggestion -> flap the status again
	# the Dismissed row is inside dismiss_cooldown_days: no new row

def test_a_rule_cannot_push_a_rep_past_the_open_cap(self):
	# rep already at max_open_per_user open suggestions: firing the rule adds none

def test_a_mutable_title_template_does_not_stack_tasks(self):
	# title_template "Follow up: {{ doc.status }}", flap status twice
	# exactly one open task exists for the record

def test_two_rules_with_the_same_title_both_create_their_task(self):
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement:**
  - New frappe-facing helper in `signals.py`, so automation shares the one lifecycle:

```python
def suggestion_blocked(signal: str, reference_docname: str, user: str | None, now=None) -> bool:
	"""Would ``dedupe`` drop this (signal, record, user) right now?

	The rule engine creates suggestions outside the hourly run, and its old
	Open-only exists check silently bypassed the dismiss/accept cooldowns and
	the repeat-dismisser multiplier — a dismissed rule suggestion came back on
	the next status flap. One candidate, same machinery.
	"""
	now = now or frappe.utils.now_datetime()
	cfg = get_signal_config()
	existing = frappe.get_all(
		"CRM Suggestion",
		filters={"signal": signal, "reference_docname": reference_docname},
		fields=["signal", "reference_docname", "user", "status", "modified"],
	)
	dismissals = _dismissal_counts([{"signal": signal, "user": user}]) if user else {}
	candidate = {"signal": signal, "reference_docname": reference_docname, "user": user}
	return not dedupe([candidate], existing, now, cfg.dismiss_cooldown_days, dismissals)


def user_at_open_cap(user: str | None, cap: int) -> bool:
	"""Is this rep's (or the unowned bucket's) open queue already full?"""
	count = frappe.db.count("CRM Suggestion", {"user": user or ("in", ("", None)), "status": "Open"})
	return count >= cap
```

  (Exact filter syntax for the unowned bucket: `{"user": ("in", ("", None))}` — verify against frappe's filter grammar in implementation; fall back to a qb query mirroring `_open_counts`.)
  - `automation.py` Create Suggestion branch: replace the `frappe.db.exists` check with `if suggestion_blocked(signal, doc.name, owner): return`, and before inserting: `if user_at_open_cap(owner, get_signal_config().max_open_per_user): return`.
  - `crm_task.json`: add a hidden provenance field (after `reference_docname` in `field_order`), bump `"modified"`:

```json
  {
   "fieldname": "automation_rule",
   "fieldtype": "Data",
   "hidden": 1,
   "label": "Automation Rule",
   "no_copy": 1,
   "read_only": 1,
   "description": "The CRM Automation Rule that created this task; the flap guard keys on it."
  }
```

  (Data, not Link: a deleted rule must not orphan-invalidate its tasks.)
  - Create Task branch: guard on rule identity, keep the title check only for pre-field legacy rows, stamp the field on insert:

```python
	if rule.action == "Create Task":
		# status flapping must not stack duplicate tasks for the same record.
		# Keyed on the rule, not the rendered title: a title template that
		# interpolates a mutable field renders differently per flap, and two
		# rules that happen to render the same title are two instructions.
		open_statuses = ("not in", ("Done", "Canceled"))
		duplicate = frappe.db.exists(
			"CRM Task",
			{
				"automation_rule": rule.name,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"status": open_statuses,
			},
		) or frappe.db.exists(
			"CRM Task",
			{
				# legacy rows from before the field existed
				"automation_rule": ("in", ("", None)),
				"title": title,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"status": open_statuses,
			},
		)
		if duplicate:
			return
		frappe.get_doc({..., "automation_rule": rule.name, ...}).insert(ignore_permissions=True)
```

- [ ] **Step 4: `migrate`, then run** `crm.tests.test_automation` + `crm.agent.tests.test_signals`. Expect PASS.
- [ ] **Step 5: Commit** `fix: rule suggestions now honour the lifecycle; the task flap guard keys on the rule`

---

### Task 8: mark_fulfilled trusts an arbitrary claim; a missed Meeting round-trips as a Task

**Findings:** `rep_plan.py:288` — `mark_fulfilled` never checks the claimed record exists, qualifies, or belongs to the caller; a bogus claim excludes the real record from its owner's matching for the whole horizon. `rep_plan.py:60` + `signals.py:111` — `Meeting → create_task → Task` is a lossy round trip; the matcher then looks for a Task and the meeting never fulfils it.

**Files:**
- Modify: `crm/api/rep_plan.py:279-303, 344-378`, `crm/agent/signals.py:390-401`, `crm/rep_planning.py` (export a doctype→kind map)
- Test: `crm/tests/test_rep_plan_api.py`, `crm/agent/tests/test_signals.py`

- [ ] **Step 1: Failing tests:**

```python
def test_mark_fulfilled_refuses_a_record_that_does_not_exist(self):
def test_mark_fulfilled_refuses_another_reps_record(self):
def test_mark_fulfilled_accepts_the_callers_own_completed_call(self):
def test_a_stale_meeting_suggestion_proposes_a_meeting_again(self):
	# stale_plan payload carries activity_type; propose_week must honour it
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement:**
  - `rep_planning.py`: `KIND_BY_DOCTYPE = {source["doctype"]: kind for kind, source in ACTUAL_SOURCES.items()}`.
  - `mark_fulfilled`: after the doctype check, validate the claim with the matcher's own definition of the rep's activity (existence + status filters + ownership in one query):

```python
	if fulfilled_by:
		kind = KIND_BY_DOCTYPE[fulfilled_by_doctype]
		if not _query_source(kind, frappe.session.user, None, names=[fulfilled_by]):
			frappe.throw(
				_("{0} {1} is not a completed {2} of yours.").format(
					fulfilled_by_doctype, fulfilled_by, kind.lower()
				)
			)
```

  - `signals.find_stale_plan_items`: `"action_payload": {"title": label, "activity_type": activity}` — the payload carries the activity so the round trip is lossless.
  - `propose_week`: prefer the payload's activity over the action mapping:

```python
	payload = _parse_payload(s.action_payload)
	activity = payload.get("activity_type")
	if activity not in ACTUAL_SOURCES:
		activity = ACTION_TO_ACTIVITY.get(s.suggested_action, "Task")
```

  (Import `ACTUAL_SOURCES` from `crm.rep_planning` — `rep_plan.py` already imports from it for `FULFILMENT_DOCTYPES`. Extract the small `_parse_payload` from `_draft_note` so both use it.)
- [ ] **Step 4: Run** `crm.tests.test_rep_plan_api`, `crm.tests.test_rep_planning`, `crm.agent.tests.test_signals`. Expect PASS.
- [ ] **Step 5: Commit** `fix: fulfilment claims are verified; a missed meeting proposes a meeting again`

---

### Task 9: context sort TypeError; prompt budgets overshoot by the join separators

**Findings:** `context.py:65` — `key=lambda c: c.get("creation") or ""` mixes `str` and `datetime` when one row's creation is NULL → TypeError → 500 out of a degrade-only tier. `model_fallback.page_text` / `context._fenced_thread` — the join separators are never charged to the budget, so output exceeds `max_chars`.

**Files:**
- Modify: `crm/agent/context.py:59-90`, `crm/domain_enrichment/model_fallback.py:199-215`
- Test: `crm/agent/tests/test_context.py`, the enrichment tests (locate `model_fallback` tests under `crm/domain_enrichment/`)

- [ ] **Step 1: Failing pure tests:**

```python
def test_a_null_creation_does_not_break_the_sort(self):
	comms = [
		{"creation": datetime(2026, 8, 1), "sender": "a", "content": "x"},
		{"creation": None, "sender": "b", "content": "y"},
	]
	build_thread_messages({"name": "D"}, comms)  # must not raise

def test_the_fence_respects_the_budget_including_separators(self):
	comms = [{"creation": f"2026-08-{i:02}", "sender": "s", "content": "c" * 40} for i in range(1, 10)]
	body = _fenced_thread(comms, max_chars=200)
	inner = body.split("\n", 1)[1].rsplit("\n", 1)[0]
	self.assertLessEqual(len(inner), 200)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement:** sort key `key=lambda c: str(c.get("creation") or "")` (a datetime's str form sorts chronologically; a NULL sorts oldest, harmless). Budget: charge `len(entry) + (1 if kept else 0)` in `_fenced_thread` (its join is `"\n"`) and `len(entry) + (2 if kept else 0)` in `page_text` (join is `"\n\n"`).
- [ ] **Step 4: Run** `crm.agent.tests.test_context` + the enrichment module tests. Expect PASS.
- [ ] **Step 5: Commit** `fix: thread sort broke on a NULL timestamp; prompt budgets ignored separators`

---

## Final gate

- [ ] Full backend suite: `... bench --site test_site run-tests --app crm` — read the real counts, expect zero failures.
- [ ] `ruff check` clean on every touched file (the PostToolUse hook formats as we go).
- [ ] Frontend suite untouched by these changes; run `yarn test:run` in the container if any doubt arises.
- [ ] `superpowers:requesting-code-review` over the branch diff before handing it over.

## Self-review notes

- Spec coverage: 10 top findings → Tasks 1,2,3,4,6,7,8; 6 cut correctness findings → Tasks 5 (leaf manager, closed-deal cleanup, 200-comm drift), 9 (context sort, budget overshoot); Task-matching on `modified` is **deliberately not changed** — the code documents the trade-off at `rep_planning.py:28-32` and `_fulfilment_holds` already compensates; it is a design decision, not a defect. 4 cleanup findings → Task 2 (concurrency), Task 3 (the copy-paste scaffold shrinks into `period_windows`), Task 5 (`visible_reps` delegation, `health_scored_on` index).
- Type consistency: `period_windows` returns strings (frappe's `add_days` returns str for str input) — matches how the tiles use the values today; `suggestion_blocked` takes `user: str | None` matching `owner`'s type in automation.
