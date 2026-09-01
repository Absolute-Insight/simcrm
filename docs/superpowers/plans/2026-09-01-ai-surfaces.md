# Mentor, Assistant and Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three model-backed surfaces — Mentor (help center), Assistant (admin-curated knowledge base), Analyst (admin-only, metrics-layer grounded) — plus the "AI & automation" help category, then audit, QA, release and upgrade production.

**Architecture:** Every surface follows the existing agent-tier contract in `crm/agent/api.py`: rate-limited, budgeted, guided-decoding into a pydantic schema, `disabled`/`unavailable` degrade statuses, model output rendered as text. Grounding is deterministic (`knowledge.select_articles` for text sources; a metric catalogue over `crm/api/dashboard.py` for the analyst). One shared chat component and a store factory on the frontend.

**Tech Stack:** Frappe 17 (pinned), Python 3.11, pydantic, MariaDB, redis; Vue 3 + frappe-ui + Tailwind; vitest; Playwright.

**Spec:** `docs/superpowers/specs/2026-09-01-ai-surfaces-design.md`

## Global Constraints

- Branch: `feat/ai-surfaces` (off `origin/develop`). Never commit on `develop`/`main` (hook refuses).
- Python tests run inside the devcontainer against `test_site`, one dotted module at a time:
  `docker exec simcrm_devcontainer-frappe-1 bash -c 'cd /home/frappe/frappe-bench && PYTHONPATH=/workspace bench --site test_site run-tests --app crm --module <dotted.module>'`
  Never pass a package to `--module` (silent false green).
- After any doctype JSON change: bump `"modified"` in the JSON, then `docker exec simcrm_devcontainer-frappe-1 bash -c 'cd /home/frappe/frappe-bench && PYTHONPATH=/workspace bench --site test_site migrate'` (and the same for `dev.localhost` if it exists — check `ls sites`).
- Frontend tests: `docker exec simcrm_devcontainer-frappe-1 bash -c 'cd /workspace/frontend && yarn test:run'`.
- Layering: `crm/agent/analyst.py` is pure (no `frappe`); `crm/agent/analyst_data.py` may import frappe and `crm.api.dashboard`. Add both to `ALLOWED_SIBLING_IMPORTS` in `crm/agent/tests/test_layering.py`.
- Model output is untrusted text: `{{ }}` only, never `v-html`, never fed back as instructions.
- No model-written SQL. The analyst runs only catalogue metrics.
- Commit style `feat:` / `fix:` / `test:` / `docs:`; one logical change per commit; trailer lines `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_013DjMH4usURNB99GSYAYBEn`.
- Coloured text uses the `-9` ink step; check both themes.

---

### Task 1: Shared chat component and store factory

**Files:**
- Create: `frontend/src/stores/agentChat.js`
- Create: `frontend/src/components/AgentChat.vue`
- Modify: `frontend/src/stores/assistant.js` (becomes an instance)
- Modify: `frontend/src/components/Assistant.vue` (uses `AgentChat`)
- Test: `frontend/tests/unit/agentChat.test.js`

**Interfaces:**
- Produces: `createChatStore({ method, mapResult, historyTurns = 8 })` → `{ visible, messages, asking, failure, ask(question), retry(), clear(), toggle() }` where `failure` is `'' | 'disabled' | 'unavailable' | 'empty'` and an ok result is mapped by `mapResult(result) → { content, ...extras }` then pushed as `{ role: 'assistant', ...mapped }`; the raw result's `reason` is stored on `failureReason`.
- Produces: `<AgentChat :messages :asking :failure :examples :intro :placeholder :compact @send @retry @clear>` with slots `message-extra="{ message }"`, `failure-actions="{ failure }"`, and `empty` (overrides the intro block).

- [ ] **Step 1: Write the failing store test**

```js
// frontend/tests/unit/agentChat.test.js
import { beforeEach, describe, expect, it, vi } from 'vitest'

const callMock = vi.fn()
vi.mock('frappe-ui', () => ({ call: (...args) => callMock(...args) }))

import { createChatStore } from '@/stores/agentChat'

describe('createChatStore', () => {
  beforeEach(() => callMock.mockReset())

  it('sends the question with the prior turns as history and appends the answer', async () => {
    callMock.mockResolvedValue({ status: 'ok', answer: 'Hi', sources: [{ name: 'a', title: 'A' }] })
    const store = createChatStore({
      method: 'crm.agent.api.ask_assistant',
      mapResult: (r) => ({ content: r.answer, sources: r.sources }),
    })
    await store.ask('hello')
    expect(callMock).toHaveBeenCalledWith('crm.agent.api.ask_assistant', {
      question: 'hello',
      history: [],
    })
    expect(store.messages.value).toEqual([
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'Hi', sources: [{ name: 'a', title: 'A' }] },
    ])
    await store.ask('again')
    expect(callMock.mock.calls[1][1].history).toEqual([
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'Hi' },
    ])
  })

  it('records disabled, empty and unavailable without an answer turn', async () => {
    const store = createChatStore({ method: 'x', mapResult: (r) => ({ content: r.answer }) })
    callMock.mockResolvedValue({ status: 'disabled', reason: 'analyst_off' })
    await store.ask('q')
    expect(store.failure.value).toBe('disabled')
    expect(store.failureReason.value).toBe('analyst_off')
    callMock.mockResolvedValue({ status: 'empty' })
    await store.ask('q2')
    expect(store.failure.value).toBe('empty')
    callMock.mockRejectedValue(new Error('boom'))
    await store.ask('q3')
    expect(store.failure.value).toBe('unavailable')
    expect(store.messages.value.filter((m) => m.role === 'assistant')).toHaveLength(0)
  })

  it('retry re-sends the last unanswered question once', async () => {
    const store = createChatStore({ method: 'x', mapResult: (r) => ({ content: r.answer }) })
    callMock.mockRejectedValueOnce(new Error('down'))
    await store.ask('q')
    callMock.mockResolvedValue({ status: 'ok', answer: 'ok' })
    await store.retry()
    expect(store.messages.value.map((m) => m.role)).toEqual(['user', 'assistant'])
  })
})
```

- [ ] **Step 2: Run it** — expected FAIL (module not found).

- [ ] **Step 3: Implement `agentChat.js`** — port `askAssistant`/`retryLastQuestion`/`clearAssistant` from `stores/assistant.js` into a factory. Keep `plainTextAnswer` out of the factory (callers apply it in `mapResult`). Then rewrite `stores/assistant.js` as:

```js
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'

const store = createChatStore({
  method: 'crm.agent.api.ask_assistant',
  mapResult: (r) => ({ content: plainTextAnswer(r.answer), sources: r.sources || [] }),
})
export const assistantVisible = store.visible
export const assistantMessages = store.messages
export const assistantAsking = store.asking
export const assistantFailure = store.failure
export const assistantFailureReason = store.failureReason
export const toggleAssistant = store.toggle
export const clearAssistant = store.clear
export const askAssistant = store.ask
export const retryLastQuestion = store.retry
```

- [ ] **Step 4: Extract `AgentChat.vue`** from `Assistant.vue`: everything inside the panel's inner column except the header. `Assistant.vue` keeps the slide-out shell, header, `onClickOutside`, and passes the store refs in. `compact` prop drops the intro paragraph spacing for the help-center pane. Keep the `disabled` copy as slot defaults; `Assistant.vue` fills `failure-actions` with the settings / help buttons it has today. Behaviour must be pixel-identical for the assistant panel.

- [ ] **Step 5: Run vitest + `yarn lint`** (inside the container). Open the app on the dev site and confirm the Assistant panel still opens, sends, shows the disabled/unavailable states.

- [ ] **Step 6: Commit** `refactor: extract the chat panel into AgentChat and a store factory`

---

### Task 2: Mentor endpoint and help-center block

**Files:**
- Modify: `crm/agent/knowledge.py` (rename `SYSTEM_PROMPT` → `MENTOR_SYSTEM_PROMPT`, `build_assistant_messages(question, articles, history, system_prompt=MENTOR_SYSTEM_PROMPT)`)
- Modify: `crm/agent/api.py` (`ask_mentor` = current `ask_assistant` body; `ask_assistant` is rewritten in Task 4)
- Rename test: `crm/agent/tests/test_assistant_api.py` → `crm/agent/tests/test_mentor_api.py` (calls `ask_mentor`)
- Modify: `crm/agent/tests/test_knowledge.py` (prompt constant name)
- Create: `frontend/src/stores/mentor.js`
- Modify: `frontend/src/components/Modals/HelpCenterModal.vue`
- Modify: `crm/help/articles/assistant.md` → moved and rewritten in Task 9; for now only fix the sidebar reference.

**Interfaces:**
- Produces: `crm.agent.api.ask_mentor(question, history)` → `{"status": "ok", "answer", "related_articles"}` | degrade statuses. Sales users only (as today).
- Produces: `stores/mentor.js` exporting `mentorMessages, mentorAsking, mentorFailure, askMentor, retryMentor, clearMentor, mentorOpen` (`mentorOpen` = boolean ref: show the transcript pane instead of the article).

- [ ] **Step 1: Move tests** — `git mv` the test file, replace `ask_assistant` with `ask_mentor`, run:
  `... --module crm.agent.tests.test_mentor_api` → expected FAIL (`ask_mentor` missing).
- [ ] **Step 2: Add `ask_mentor`** to `api.py` with the old body (whitelist, `@sales_user_only`, `@rate_limit`). Leave `ask_assistant` in place temporarily delegating to `ask_mentor` so the frontend keeps working until Task 4.
- [ ] **Step 3: Run test module** → PASS. Run `test_knowledge` → PASS after the rename.
- [ ] **Step 4: Frontend** — `stores/mentor.js`:

```js
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'
import { ref } from 'vue'
const store = createChatStore({
  method: 'crm.agent.api.ask_mentor',
  mapResult: (r) => ({ content: plainTextAnswer(r.answer), relatedArticles: r.related_articles || [] }),
})
export const mentorOpen = ref(false)
export const mentorMessages = store.messages
export const mentorAsking = store.asking
export const mentorFailure = store.failure
export const clearMentor = store.clear
export const retryMentor = store.retry
export async function askMentor(q) { mentorOpen.value = true; return store.ask(q) }
```

  `HelpCenterModal.vue`: above the search `TextInput` add a Mentor block — a `TextInput` with a `SparkleIcon` prefix, placeholder "Ask the mentor how Vectora works", `@keydown.enter` → `askMentor`. When `mentorOpen && mentorMessages.length` the right pane renders `<AgentChat compact :messages="mentorMessages" ... @send="askMentor" @retry="retryMentor" @clear="clearMentor">` with a header row "Mentor" and a "Clear" ghost button; `message-extra` slot renders the related-article chips (`Button variant="subtle"` with `LucideBookOpen`) whose click sets `activeHelpArticle` and `mentorOpen = false`. Selecting an article in the tree also sets `mentorOpen = false`; while a transcript exists and an article is shown, a small "Back to the mentor" `Button variant="ghost"` sits at the top of the article pane. Reset `mentorOpen` on dialog open (keep the transcript).
- [ ] **Step 5: Manual check** in both themes on the dev site; `yarn lint`.
- [ ] **Step 6: Commit** `feat: the Mentor answers how Vectora works from inside the help center`

---

### Task 3: `CRM Knowledge Article` doctype, settings field, sample pack loader

**Files:**
- Create: `crm/fcrm/doctype/crm_knowledge_article/{__init__.py,crm_knowledge_article.json,crm_knowledge_article.py}`
- Modify: `crm/agent/doctype/crm_agent_settings/crm_agent_settings.json` (add `assistant_reads_products` Check and `analyst_enabled` Check in a new "Assistant & analyst" section; bump `modified`)
- Modify: `crm/agent/config.py` (`AgentConfig.assistant_reads_products: bool = False`, `analyst_enabled: bool = False`, read in `from_settings` with `to_int`)
- Modify: `crm/agent/api.py::get_settings` (return both new ints) and `crm/api/settings.py` or wherever the settings page saves (check `AssistantSettings.vue` — it saves via `frappe.client.set_value` on the Single; no server change needed for save)
- Create: `crm/knowledge/__init__.py` (sample loader) and `crm/knowledge/samples/*.md`
- Test: `crm/tests/test_knowledge_samples.py`

**Interfaces:**
- Produces doctype fields: `title` (Data, reqd), `category` (Data), `tags` (Data), `product` (Link CRM Product), `available_to_assistant` (Check, default 1), `body` (Markdown Editor, reqd). `autoname: "format:KB-{#####}"`. Permissions: System Manager all; Sales Manager, Sales User read. `track_changes: 1`.
- Produces: `crm.knowledge.load_samples() -> list[dict]` — `{name, title, category, tags, product, content}` parsed with `crm.help.parse_article` semantics but its own category check (any non-empty category) — implement `parse_sample(name, text)` locally rather than importing the help parser's category rule.
- Produces: `AgentConfig.assistant_reads_products`, `AgentConfig.analyst_enabled`.

- [ ] **Step 1: Test the loader**

```python
# crm/tests/test_knowledge_samples.py
from frappe.tests import UnitTestCase
from crm.knowledge import load_samples, parse_sample

class SamplePackTest(UnitTestCase):
	def test_every_sample_parses_and_is_marked_as_sample(self):
		samples = load_samples()
		self.assertGreaterEqual(len(samples), 12)
		for s in samples:
			self.assertTrue(s["title"] and s["category"] and s["content"])
			self.assertIn("sample content", s["content"].lower()[:400])

	def test_parse_sample_reads_optional_tags_and_product(self):
		s = parse_sample("x", "---\ntitle: T\ncategory: C\ntags: a, b\n---\nbody")
		self.assertEqual(s["tags"], "a, b")
		self.assertEqual(s["product"], "")
		self.assertEqual(s["content"], "body")

	def test_parse_sample_refuses_missing_title(self):
		with self.assertRaises(ValueError):
			parse_sample("x", "---\ncategory: C\n---\nbody")
```

- [ ] **Step 2: Run** → FAIL. **Step 3:** write `crm/knowledge/__init__.py` (frappe-free; `SAMPLES_DIR = Path(__file__).parent / "samples"`, `load_samples()` sorted by filename, `parse_sample` as above) and the sample files. Write the samples in `crm/knowledge/samples/` — at least these 14, each starting with a one-line italic note "*Sample content — replace with your own product knowledge.*":
  `01-ball-valves.md`, `02-butterfly-valves.md`, `03-gate-valves.md`, `04-globe-valves.md`, `05-check-valves.md`, `06-knife-gate-valves.md`, `07-control-valves.md`, `08-relief-and-safety-valves.md`, `09-actuators.md`, `10-flow-meters.md`, `11-materials-and-trims.md`, `12-pressure-classes-and-end-connections.md`, `13-standards-and-certifications.md`, `14-selection-guide-by-industry.md`. Categories: "Valves", "Actuation & instrumentation", "Engineering reference", "Selection guides". Each article: what it is, typical sizes and pressure classes, materials, where it is used (industries, example application types such as mine slurry lines, potable water reticulation, refinery isolation), pros and limits, "questions to ask the customer", and standards. Tags line with synonyms (e.g. `tags: ball valve, floating ball, trunnion, quarter-turn, isolation`). Accurate generic engineering content, no invented product codes.
- [ ] **Step 4: Doctype JSON + config** — create the doctype JSON by hand (copy the structure of `crm_quota.json` for the envelope), add the two settings fields, update `AgentConfig` and `DEFAULT_SETTINGS`, `get_settings`. Migrate `test_site`. Run `crm.agent.tests.test_config` and `test_settings` → PASS.
- [ ] **Step 5: Commit** `feat: CRM Knowledge Article doctype and the sample valve knowledge pack`

---

### Task 4: Knowledge API and the Assistant over the knowledge base

**Files:**
- Create: `crm/api/knowledge.py`
- Modify: `crm/agent/knowledge.py` (`ASSISTANT_SYSTEM_PROMPT`, `article_from_product(row, currency)`, tags folded into scoring)
- Modify: `crm/agent/api.py::ask_assistant` (rewrite), `crm/agent/tests/test_layering.py` unchanged (no new sibling imports)
- Test: `crm/agent/tests/test_assistant_api.py` (new), `crm/tests/test_knowledge_api.py`, `crm/agent/tests/test_knowledge.py` (tags/product scoring)

**Interfaces:**
- Produces: `crm.api.knowledge.list_articles()` → `{"articles": [{name,title,category,tags,product,available_to_assistant,body,modified}]}` (read permission; any CRM user). `save_article(doc)` (System Manager; `doc` is a dict with optional `name` → update else insert; returns the saved dict). `delete_article(name)` (System Manager). `import_samples()` (System Manager, `user_rate_limited("crm_knowledge_import", 6)`) → `{"imported": n, "skipped": m}` skipping existing titles (case-insensitive).
- Produces: `crm.agent.api.ask_assistant(question, history)` → `{"status": "ok", "answer", "sources": [{"name","title"}]}` | `{"status": "empty"}` | `disabled` | `unavailable`.
- Produces: `knowledge.score_article` counts a `tags` string like extra title text.

- [ ] **Step 1: Failing tests** — in `test_assistant_api.py` (IntegrationTestCase, stub `client.complete`): (a) with no knowledge articles → `{"status": "empty"}` and the model never called; (b) an article with `available_to_assistant=0` is not in the prompt (assert on `complete.call_args[0][2][0]["content"]`); (c) sources are filtered to loaded names and carry titles; (d) with `assistant_reads_products=1` (patch `get_config`) an enabled `CRM Product` appears in the prompt as `## Article \`product:<name>\``. In `test_knowledge_api.py`: `import_samples` twice → second call `imported == 0`; `save_article` as a Sales User raises `PermissionError` (use `frappe.set_user` with a fixture user created via `frappe.get_doc({"doctype":"User", ...}).insert()` with role Sales User, or reuse an existing test user helper if `crm/tests` has one — check `crm/tests/test_quota.py` for the pattern).
- [ ] **Step 2: Run both modules** → FAIL. **Step 3: Implement.** `ask_assistant`: gate → `frappe.get_list("CRM Knowledge Article", filters={"available_to_assistant": 1}, fields=[...], limit=500)` → article dicts `{name, title, content: body, tags}`; if `cfg.assistant_reads_products`: `frappe.get_list("CRM Product", filters={"disabled": 0}, fields=["name","product_code","product_name","description","standard_rate"], limit=500)` → `article_from_product` (`name: f"product:{row.name}"`, `title: product_name`, `content: f"Product code {code}. {strip_html(description)}. Standard rate {rate} {currency}."`). Empty combined list → `{"status": "empty"}`. Select, build messages with `ASSISTANT_SYSTEM_PROMPT`, complete `AssistantAnswer`, map `related_articles` → `sources` by lookup.
  `ASSISTANT_SYSTEM_PROMPT`: "You are the sales assistant for {company}'s reps, answering questions a customer might ask about the company's products, models, materials, standards and the industries that use them. Answer only from the knowledge base below. If it does not cover the question, say so and suggest what to check with engineering — never guess a specification, rating or price. Be concise and concrete; a rep may be reading this while on a call. Reply only with JSON matching the schema: `answer` is plain text; `related_articles` names up to 3 provided articles by `name`." (`{company}` from `frappe.db.get_single_value("FCRM Settings", "brand_name")` or "the company"; pass as a parameter into the pure builder.)
- [ ] **Step 4: Run modules** → PASS. Also `crm.agent.tests.test_knowledge`, `test_layering`.
- [ ] **Step 5: Commit** `feat: the Assistant answers from the admin-curated knowledge base`

---

### Task 5: Settings → Knowledge page and the Assistant panel copy

**Files:**
- Create: `frontend/src/components/Settings/KnowledgeSettings.vue`, `frontend/src/components/Modals/KnowledgeArticleModal.vue`
- Modify: `frontend/src/components/Settings/Settings.vue` (register "Knowledge" under System Configuration, admin-only, `PhBookOpenText` icon), `AssistantSettings.vue` (two new switches: "Let the assistant read the product catalogue", "Allow the analyst to read CRM and ERP data" with descriptions), `frontend/src/components/Assistant.vue` (intro, examples, `empty` failure state with admin button to the Knowledge page, sources chips)
- Test: none new (no pure logic); manual QA.

- [ ] **Step 1: KnowledgeSettings.vue** — `createResource` on `crm.api.knowledge.list_articles`; header with title, a `TextInput` search (client-side over title/tags/body), buttons **New article** and **Import sample knowledge** (confirm dialog explaining what it adds; after success `toast.success(__('{0} articles imported, {1} already existed', [...]))`). List grouped by category, each row: title, tags as small badges, a `Switch` bound to `available_to_assistant` (saves immediately via `save_article`), edit and delete icons. `KnowledgeArticleModal.vue`: `Dialog` with title, category, tags, product (`Link` control to CRM Product), available switch, body `TextEditor`? No — the body is markdown: use a `textarea` with monospace font and a "Preview" toggle rendering through `sanitizeHTML(renderArticleMarkdown(body))` (the help-center rule).
- [ ] **Step 2: Assistant.vue** — intro: "Ask about our products, models, materials, standards and which industries use what. Answers come only from the knowledge base your administrator maintains." Examples: "Which valve do we recommend for mine slurry lines?", "What pressure classes do our gate valves come in?", "Which standards do our valves comply with?". `empty` state copy: admin → "No knowledge has been added yet." + button "Open Settings → Knowledge"; others → "Your administrator has not added product knowledge yet." Sources render as non-clickable `Badge`s titled with the source title.
- [ ] **Step 3: Sidebar label stays "Assistant"**; help-center references updated in Task 9.
- [ ] **Step 4: Manual QA** both themes: import samples, toggle one off, ask a question on the dev site with the live model (`ollama` at `http://host.docker.internal:11435/v1`? — check `CRM Agent Settings` on `test_site`/dev site first; the devcontainer can reach the host's `sim-ollama` on `127.0.0.1:11435` only through the host gateway). Confirm `yarn lint`.
- [ ] **Step 5: Commit** `feat: Settings → Knowledge curates what the Assistant may say`

---

### Task 6: Analyst — pure catalogue, plan normalisation, projection, prompts

**Files:**
- Create: `crm/agent/analyst.py`
- Modify: `crm/agent/schemas.py` (`AnalystPlan`, `AnalystAnswer`)
- Modify: `crm/agent/tests/test_layering.py` (`"analyst": {"schemas"}`, `"analyst_data": {"analyst", "config", "signals", "predict"}`)
- Test: `crm/agent/tests/test_analyst.py` (UnitTestCase, no site)

**Interfaces:**
- Produces: `CATALOGUE: dict[str, Metric]` where `Metric = {"title": str, "description": str, "source": "crm"|"erp", "columns": list[{"key","label","type"}]}` (types: `text`, `int`, `currency`, `percent`, `date`, `month`).
- Produces: `available_keys(erp_enabled: bool) -> list[str]`.
- Produces: `normalise_plan(plan: AnalystPlan | None, available: list[str], today: date) -> dict` → `{"metrics": [...≤4], "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD"}` (defaults: last 12 full months up to today; swapped if reversed; unknown keys dropped; empty → `fallback_plan`).
- Produces: `fallback_plan(question: str, available: list[str]) -> list[str]` keyword map (revenue/sales/cash → `won_revenue_by_month`, `erp_cashflow_by_month` if available; forecast/project/next → `forecast_by_month`, `revenue_projection`; quota/target/behind → `quota_attainment_by_rep`; risk/slip/quiet/maintenance → `deals_at_risk`, `accounts_going_quiet`; pipeline/stage → `pipeline_by_stage`; funnel/conversion → `funnel_conversion`; industry/territory/rep/source → the matching breakdown; growth → `growth_rates`; default `won_revenue_by_month`, `pipeline_by_stage`).
- Produces: `project_revenue(series: list[tuple[str, float]], horizon: int = 3) -> dict` → `{"points": [{"month","value","kind": "actual"|"projected"}], "slope_per_month": float, "method": "least squares over N months"}`, values clamped at 0, `series` months as `YYYY-MM`.
- Produces: `growth_rates(series) -> list[{"month","value","change_pct"}]` (`None` for the first month or a zero base).
- Produces: `build_plan_messages(question, available_metrics: list[dict], today, history) -> list[dict]`, `build_answer_messages(question, tables: list[dict], period, history) -> list[dict]`. The answer system prompt contains the sentence: "Every number in your answer must appear in the FIGURES block; if the figures do not answer the question, say 'The data does not cover that.'"

- [ ] **Step 1: Tests** (write all, run, expect FAIL):

```python
class NormalisePlanTest(UnitTestCase):
	def test_unknown_metrics_are_dropped_and_the_period_defaults(self):
		plan = AnalystPlan(metrics=["won_revenue_by_month", "nope"], from_date="", to_date="", reasoning="")
		out = normalise_plan(plan, ["won_revenue_by_month"], date(2026, 9, 1))
		self.assertEqual(out["metrics"], ["won_revenue_by_month"])
		self.assertEqual(out["from_date"], "2025-09-01")
		self.assertEqual(out["to_date"], "2026-09-01")

	def test_reversed_dates_are_swapped_and_more_than_four_metrics_are_capped(self): ...
	def test_empty_selection_falls_back_by_keyword(self):
		out = normalise_plan(AnalystPlan(metrics=[], from_date="", to_date="", reasoning=""), available_keys(False), date(2026, 9, 1), question="are we behind quota?")
		self.assertEqual(out["metrics"], ["quota_attainment_by_rep"])

class ProjectionTest(UnitTestCase):
	def test_a_rising_series_projects_upward_and_labels_points(self):
		out = project_revenue([("2026-06", 100.0), ("2026-07", 200.0), ("2026-08", 300.0)], horizon=2)
		self.assertEqual([p["month"] for p in out["points"]], ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"])
		self.assertAlmostEqual(out["points"][3]["value"], 400.0)
		self.assertEqual(out["points"][3]["kind"], "projected")
	def test_a_falling_series_never_projects_below_zero(self): ...
	def test_fewer_than_two_points_yields_no_projection(self): ...

class PromptTest(UnitTestCase):
	def test_answer_prompt_carries_the_figures_and_the_no_invention_rule(self): ...
	def test_plan_prompt_lists_only_available_metrics(self): ...
```

- [ ] **Step 2: Implement** `analyst.py` and the schemas:

```python
class AnalystPlan(BaseModel):
	model_config = ConfigDict(extra="forbid")
	metrics: list[str] = Field(default_factory=list, max_length=6)
	from_date: str = ""
	to_date: str = ""
	reasoning: str = Field(default="", max_length=300)

class AnalystAnswer(BaseModel):
	model_config = ConfigDict(extra="forbid")
	answer: str = Field(min_length=1, max_length=4000)
	highlights: list[str] = Field(default_factory=list, max_length=5)
	caveats: list[str] = Field(default_factory=list, max_length=3)
```

  Month arithmetic without frappe: `datetime.date` + a small `add_months` helper. Dates parsed with `date.fromisoformat` in a try/except → default.
- [ ] **Step 3: Run** `crm.agent.tests.test_analyst`, `test_schemas`, `test_layering` → PASS.
- [ ] **Step 4: Commit** `feat: analyst catalogue, plan normalisation and revenue projection`

---

### Task 7: Analyst data layer (CRM metrics + ERP adapters)

**Files:**
- Create: `crm/agent/analyst_data.py`
- Test: `crm/agent/tests/test_analyst_data.py` (IntegrationTestCase; ERP adapters stubbed)

**Interfaces:**
- Produces: `run_plan(plan: dict, erp: str | None) -> list[dict]`, each table `{"key","title","source": "CRM"|"Acumatica"|"ERPNext","columns","rows","period": {"from","to"},"note": str,"error": str | None}`. `erp` is `"acumatica"`, `"erpnext"` or `None` from `enabled_erp()`.
- Produces: `enabled_erp() -> str | None` reading `CRM Acumatica Settings.enabled` then `ERPNext CRM Settings.enabled`.
- CRM runners (all call `crm.api.dashboard` under the session user, `user=None`, `territory=None`):
  - `won_revenue_by_month` → `actual_by_month(from, to)` → rows `{month, value}` filled for every month in the window (0 for settled months).
  - `forecast_by_month` → `forecast_by_month(from, to)`; `pipeline_by_stage` → `pipeline_by_stage(from, to)`; `funnel_conversion` → `get_funnel_conversion(...)["data"]`; `leads_by_source`, `deals_by_industry`, `deals_by_territory`, `deals_by_salesperson` → their `["data"]`; `sales_trend` → `get_sales_trend(...)["data"]` aggregated to months; `growth_rates` → `analyst.growth_rates` over won revenue; `average_deal_value` and `time_to_close` → the tile dict as one row `{metric, value}`; `quota_attainment_by_rep` → `crm.api.reports._quota_attainment_by_rep(from, to, None)`; `plan_adherence_by_rep` → `crm.api.reports._plan_adherence_by_rep(...)`; `deals_at_risk` → `crm.api.dashboard._at_risk_deals(to)` rows `{deal, organization, owner, health_score, idle_days, expected_closure_date}`; `revenue_projection` → `analyst.project_revenue` over won revenue; `accounts_going_quiet` → open deals via `signals._working_deal_rows()`, `signals._activity_history` + `signals.cadence_ratio` per deal and `predict.get_deal_health(name)["score"]`, keep `ratio >= predict.COOLING_RATIO` or `days_to_close <= horizon` with slip factor, grouped by organization: rows `{organization, deals, days_since_contact, lowest_health, reason}` (cap 200 deals; sort by lowest health).
- ERP adapters: `acumatica_invoices(from, to)`, `acumatica_payments(from, to)` using `AcumaticaClient(frappe.get_cached_doc("CRM Acumatica Settings")).iter_all("SalesInvoice", filter=f"Date ge datetimeoffset'{from}T00:00:00Z' and Date le datetimeoffset'{to}T23:59:59Z'", select="Date,Amount,Balance,Status,Type")` and `"Payment"` with `ApplicationDate,PaymentAmount,Type`; `erpnext_invoices/payments` via `requests.get(f"{url}/api/resource/Sales Invoice", params={"fields": json.dumps([...]), "filters": json.dumps([["posting_date","between",[from,to]],["docstatus","=",1]]), "limit_page_length": 5000}, headers={"Authorization": f"token {key}:{secret}"}, timeout=30)`. Derived tables: `erp_invoices_by_month {month, invoiced, invoices}`, `erp_payments_by_month {month, received, payments}`, `erp_receivables {bucket: current/overdue, amount, invoices}` (overdue = `Balance > 0 and Date < today - 30`; ERPNext: `outstanding_amount > 0 and due_date < today`), `erp_cashflow_by_month {month, invoiced, received, net}`. Any exception → `error: "unreachable"`, `rows: []`, logged with `frappe.log_error(title="CRM analyst ERP read failed")`.

- [ ] **Step 1: Tests** — (a) `run_plan({"metrics": ["won_revenue_by_month"], ...}, None)` on a site with one Won deal closed in-window returns that month's value and zero-filled months (create the deal in the test, use `frappe.db.rollback` semantics of IntegrationTestCase); (b) an unknown key is ignored; (c) `erp_cashflow_by_month` with `acumatica_invoices` and `acumatica_payments` patched to return fixture rows sums correctly per month; (d) the adapter raising `AcumaticaError` yields `error == "unreachable"` and the CRM table still returns; (e) `enabled_erp()` returns `None` with both integrations off.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `test_analyst_data`, `test_layering` → PASS.
- [ ] **Step 5: Commit** `feat: analyst data layer over the metrics layer and the ERP integrations`

---

### Task 8: `ask_analyst` endpoint

**Files:**
- Modify: `crm/agent/api.py`
- Test: `crm/agent/tests/test_analyst_api.py`

**Interfaces:**
- Produces: `crm.agent.api.ask_analyst(question, history)` → `{"status": "ok", "answer", "highlights", "caveats", "tables", "period", "sources": ["CRM", ...]}` | `{"status": "disabled"}` | `{"status": "disabled", "reason": "analyst_off"}` | `{"status": "unavailable"}`. `frappe.only_for("System Manager", True)` first; `@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)`; `_throttled` once; one slot held across both completes; a `SchemaMismatch` on the *plan* call falls back to `fallback_plan` rather than degrading; a failure on the *answer* call degrades to `unavailable`.

- [ ] **Step 1: Tests** — (a) a Sales User (non-System-Manager) → `PermissionError`; (b) Administrator with `analyst_enabled=False` → `{"status":"disabled","reason":"analyst_off"}` and the model never called; (c) plan call raising `SchemaMismatch` still produces an answer using the fallback (patch `analyst_data.run_plan` to return a fixture table; `client.complete` side_effect `[SchemaMismatch("x"), AnalystAnswer(...)]`); (d) happy path returns tables from `run_plan` verbatim and `sources` deduplicated in order; (e) answer call raising `AgentUnavailable` → `unavailable`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: PASS.** Also `bench --site test_site run-tests --app crm --module crm.agent.tests.test_api` still green.
- [ ] **Step 5: Commit** `feat: ask_analyst answers admins from computed figures only`

---

### Task 9: Analyst page, route, sidebar entry

**Files:**
- Create: `frontend/src/pages/Analyst.vue`, `frontend/src/stores/analyst.js`, `frontend/src/utils/analystTables.js`
- Modify: `frontend/src/router.js` (route `/analyst`, name `Analyst`, `beforeEnter` → `usersStore().isAdmin()` else redirect to `Dashboard`), `frontend/src/components/Layouts/AppSidebar.vue` (entry "Analyst" after Reports with `condition: () => isAdmin()`, icon `PhChartLineUp`; check how `condition` is consumed at line ~590 and mirror it), `frontend/src/components/Settings/AssistantSettings.vue` (already has the switch from Task 5)
- Test: `frontend/tests/unit/analystTables.test.js`

**Interfaces:**
- Produces: `formatTable(table, currency) -> { title, source, columns: [{key,label,align}], rows: [[cell...]], csv: () => string }` using `formatCell`/`toCsv` from `utils/reportExport.js`; month cells render `MMM yyyy`; `error` tables produce a single note row.

- [ ] **Step 1: Test `formatTable`** (currency and percent cells formatted, month label, error → note, csv header line). **Step 2:** implement. **Step 3:** page: two-column layout like Reports (`LayoutHeader` with breadcrumbs "Analyst"), the transcript centred (max-w-3xl); each assistant turn: narrative (`whitespace-pre-wrap`), highlights as a bulleted list, caveats in an orange-9 note, then each table in a card with the source badge ("CRM" / "Acumatica" / "ERPNext"), period, a `ListView`-free simple `<table>` styled like the help center tables, and an "Export CSV" `Button` (`downloadCsv` helper — check `Reports.vue` for the existing download function and reuse it). Grant state: when `failure === 'disabled' && failureReason === 'analyst_off'` show "The analyst is switched off. Turn on *Allow the analyst to read CRM and ERP data* in Settings → Assistant." with a button opening that settings page. Examples as in the spec; the ERP example only when `sources` of any prior answer include an ERP or when `crm.api.knowledge`… simpler: always show four CRM examples plus the ERP one labelled "(needs an ERP connection)".
- [ ] **Step 4:** Manual QA both themes with the live model: ask the four examples; verify tables match the Reports page for the same period (quota attainment by rep).
- [ ] **Step 5: Commit** `feat: the Analyst page for administrators`

---

### Task 10: Help center — "AI & automation" category and articles

**Files:**
- Modify: `crm/help/__init__.py` (`CATEGORY_ORDER` = Getting started, Working with records, Proactive selling, Analytics & reporting, AI & automation, Customisation)
- Modify frontmatter of `assistant.md` (→ delete, replaced), `customisation.md`, `form-scripts.md`, `integrations.md` (→ Customisation), `automation-rules.md`, `suggestions.md`, `deal-health.md`, `digests.md` (→ AI & automation where they explain automatic behaviour; keep `suggestions.md`/`deal-health.md` under Proactive selling but add the three headings)
- Create: `crm/help/articles/ai-and-automation.md` (order 1), `mentor.md` (2), `assistant.md` (3, rewritten), `analyst.md` (4), `knowledge-base.md` (5), `automation-rules.md` stays (6)
- Modify: `welcome.md` (link the map), `frontend/src/components/Assistant.vue`/`HelpCenterModal.vue` example questions if they cite article names
- Test: `crm/tests/test_help.py` (existing loader test must still pass; add an assertion that every article in "AI & automation" contains the three headings `## What it does for you`, `## When it runs`, `## What it never does`)

- [ ] **Step 1:** add the assertion test → FAIL. **Step 2:** write the articles. `ai-and-automation.md` opens with a plain-language paragraph ("Vectora does two kinds of work for you without being asked…") and a table: Capability · Kind (Automatic rule / Uses a model) · What it does · Where you see it, covering: signals & suggestions, deal health, planner proposals & plan-vs-actual, forecasts & weekly snapshots, quota attainment, report digests, automation rules, SLA & assignment, website enrichment, ERP sync (Acumatica/ERPNext), Mentor, Assistant, Analyst, thread summaries, reply drafts. Then a short "How to think about model answers" section (proposal to check, never a fact; numbers in the Analyst come from Vectora's own calculations, the words come from the model). Each new article follows the three headings; `analyst.md` states cashflow and maintenance definitions honestly (CRM: won revenue and weighted forecast; accounts going quiet; ERP: invoices, payments, receivables when connected; equipment maintenance is not available without installed-base data).
- [ ] **Step 3:** run `crm.tests.test_help`, `crm.agent.tests.test_knowledge` → PASS; open the help center and click every new article in both themes.
- [ ] **Step 4: Commit** `docs: explain every automatic and model-backed capability in the help center`

---

### Task 11: Audit and fixes

- [ ] **Step 1:** Run `/security-review` on the branch. Dispatch four read-only `Explore`/`general-purpose` agents in parallel with these briefs, each returning `file:line`, the concrete failure scenario, and a proposed fix:
  1. Every `@frappe.whitelist` in `crm/` — is the permission gate explicit (`only_for`, `has_permission`, `sales_user_only`, permission-checked `get_list`)? Flag `allow_guest`, `ignore_permissions=True`, raw SQL with interpolation, `frappe.db.sql` with f-strings.
  2. Every `v-html`, `innerHTML`, `sanitizeHTML` bypass, `window.open` with user data, and every place model output or email content reaches the DOM in `frontend/src`.
  3. Rate limits and budgets on every outbound call (`requests.`, `client.complete`, enrichment, ERP, lead syncing) and every scheduler job's failure isolation.
  4. Query hot spots: N+1 in `crm/api/*.py` list endpoints and `signals.py`; bundle: `yarn build` size report, lazy-loaded routes, duplicate icon packs.
- [ ] **Step 2:** Verify each finding by reading the code yourself; discard false positives; record the list in the report notes (`docs/superpowers/plans/2026-09-01-ai-surfaces-audit.md`).
- [ ] **Step 3:** Fix each confirmed finding in its own `fix:` commit with a test where the finding is testable.

---

### Task 12: Test suites and browser QA

- [ ] **Step 1:** `/test` — vitest, `bench --site test_site run-tests --app crm` (grep every `Ran` line; four blocks), Playwright e2e. Fix anything red.
- [ ] **Step 2:** Playwright browser pass on the dev site (`http://localhost:8080/crm` via the vite server, or the built app on `:8000`), both themes: help center Mentor block (ask, chips, back), Assistant (empty state → import samples → answer with sources), Settings → Knowledge (create, toggle, delete, import), Analyst (grant off → on, four examples, CSV export), and the existing smoke paths (leads list, deal page, dashboard, reports, planner). Screenshot each surface for the report.
- [ ] **Step 3:** Commit any fixes; push; open the PR to `develop` with the summary; wait for CI (Frontend, Server, UI Tests, CodeQL, Semgrep) green; merge with a merge commit.

---

### Task 13: Release and production upgrade

- [ ] **Step 1:** `/release` — promote `develop` to `main`, confirm semantic-release tags v3.7.0, dispatch `builds.yml --ref v3.7.0`, verify the manifest returns 200 in ghcr, back-merge the bump.
- [ ] **Step 2:** **Stop and confirm with the user before touching prod.** Then, in `deploy/`: `docker compose exec backend bench --site all backup --with-files`; set `VECTORA_TAG=v3.7.0` in `.env` and update every image line in `docker-compose.override.yml` (per its own comment, `.env` should then be one release behind — put `.env` at v3.6.1 and the override at v3.7.0); `set-maintenance-mode on`; `docker compose pull`; `docker compose up -d`; `bench --site all migrate`; `set-maintenance-mode off`; wait 60 s; `bench --site <site> doctor`; `curl -sI https://vectora.absolute-insight.ai/assets/crm/frontend/sw.js | grep -i service-worker-allowed`.
- [ ] **Step 3:** As Administrator on prod: import the sample knowledge, switch on the analyst grant and the product-catalogue read, run Test connection. Playwright pass on the public site: login, Mentor, Assistant, Analyst with the live model, dashboard, reports, a deal page. Screenshots.

---

### Task 14: Report

- [ ] Load `artifact-design`, write the HTML report (what shipped with screenshots, how to demo each surface, audit findings and fixes, test counts, prod verification, exclusions and follow-ups) to the scratchpad, publish with the Artifact tool, and hand the user the link.
