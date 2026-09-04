# Rep App Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the nine gaps between Vectora and the rep app MBP uses today, so a rep can do everything they did in it — and the things it could not do — in Vectora.

**Architecture:** Model changes first (a `Visit` activity kind, a `Rescheduled` task status, a required closing note) so reps never generate history in the old shape; then the surfaces over them (unplanned-visit logging, task history, lead fields, code search); then the two reporting aggregates, which go in `crm/api/dashboard.py` because `crm/api/reports.py` may not aggregate. Nothing here is architectural — the matcher, hierarchy scoping and the one-source-of-numbers rule are all reused, not changed.

**Tech Stack:** Frappe (Python, tabs), Vue 3 + frappe-ui, `frappe.qb`, `frappe.tests.UnitTestCase` / `IntegrationTestCase`, vitest for pure JS.

**Spec:** `docs/superpowers/specs/2026-09-04-rep-app-replacement-design.md` — read it first. Gap numbers (G1–G9) below are the spec's.

## Global Constraints

Copied from the spec and the repo's conventions. Every task's requirements include these.

- **Sequencing is forced:** Tasks 1–4 (G1, G3, G4) change the data model and land before anything that writes activity. G6 depends on the import plan's custom fields existing. G5 depends on G3.
- **Reports contain no aggregation.** A new number is a function in `crm/api/dashboard.py`; `crm/api/reports.py` only consumes it. Tile and report must agree, and a test says so.
- **Scoping follows the sales hierarchy.** Any per-rep aggregate filters by `visible_reps()` exactly as `plan_adherence` does.
- **One record fulfils one plan item, ever.** An `Event` must be emitted by the matcher under exactly one kind. `Visit` is an Event with `event_category = "Visit"`, its own category added to `Event.event_category`'s options by a Property Setter; `Meeting` excludes that category. Frappe stores the first option, `"Event"`, for any event saved without a category, so existing events stay Meetings.
- **A note is required on the *transition* into a closed status** (Done, Canceled, Rescheduled), not on insert. Demo seeding and the matcher's tests create tasks directly as Done and must keep working.
- **Doctype JSON edits update both `fields` and `field_order`.** Frappe ignores a field missing from `field_order`.
- **Quick-entry layouts are stored documents** (`CRM Fields Layout`), so a new field reaches existing sites through a patch, and fresh installs through `crm/install.py`.
- **Don't rebuild the monthly activity donuts.** Deliberate; see the spec.
- **Coloured text uses the `-9` ink step** (`AGENTS.md`).
- **Frontend unit tests cover pure utils only.** Component changes get a manual check step in the running app (`/dev-up`, then the page named in the step).
- **Python is tab-indented.** Run ruff before committing. Frontend: prettier/eslint run in the pre-commit hook.
- **Tests run in the devcontainer** at `/home/frappe/frappe-bench` against `test_site`. Frontend tests: `cd /workspace/frontend && yarn test:run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `crm/fcrm/doctype/crm_rep_plan_item/crm_rep_plan_item.json` (modify) | `Visit` in `activity_type` |
| `crm/rep_planning.py` (modify) | `Visit` source; `Meeting` excludes it |
| `crm/api/rep_plan.py` (modify) | `mark_fulfilled` resolves the kind from the item; new `log_unplanned_visit` |
| `crm/tests/test_rep_planning.py`, `crm/tests/test_rep_plan_api.py` (modify) | matcher and endpoint tests |
| `frontend/src/pages/Planner.vue` (modify) | `Visit` option and icon; "Log a visit" button |
| `crm/fcrm/doctype/crm_task/crm_task.json`, `crm_task.py`, `test_crm_task.py` (modify) | `Rescheduled`; `closing_note`; `track_changes` |
| `frontend/src/components/Icons/TaskStatusIcon.vue` (modify) | glyph for `Rescheduled` |
| `crm/install.py` (modify) | `append_to_layout_column` helper; `ensure_sa_provinces`; default layouts gain the new fields |
| `crm/patches/v1_0/add_closing_note_to_task_quick_entry.py` (create) | existing sites' task layout |
| `crm/patches/v1_0/add_person_fields_to_lead_quick_entry.py` (create) | existing sites' lead layout |
| `crm/patches/v1_0/ensure_sa_provinces.py` (create) | provinces as territories on existing sites |
| `crm/patches.txt` (modify) | register the three |
| `crm/api/task.py` (create) | `get_history` |
| `frontend/src/components/Modals/DoctypeModal.vue` (modify) | history panel for tasks |
| `crm/fcrm/doctype/crm_lead/crm_lead.json` (modify) | `birthday`, `contact_type` |
| `crm/api/organization.py` (create) | `find_by_code` |
| `frontend/src/pages/Organizations.vue` (modify) | code search box |
| `crm/api/dashboard.py` (modify) | `activity_cancellations`, `client_reliability`; `plan_adherence` gains `cancelled` |
| `crm/api/reports.py` (modify) | `cancelled` column; `client_reliability` report |
| `crm/tests/test_reports.py`, `crm/tests/test_dashboard.py` (modify) | agreement tests |
| `frontend/src/router.js` (modify) | reps land on the Planner |
| `.pi/feats/planning/README.md`, `.pi/feats/reporting/README.md` (modify) | docs |

---

### Task 1: `Visit` is an activity kind the matcher understands (G1, backend)

**Files:**
- Modify: `crm/fcrm/doctype/crm_rep_plan_item/crm_rep_plan_item.json`
- Modify: `crm/rep_planning.py:33-74`
- Modify: `crm/api/rep_plan.py:285-322` (`mark_fulfilled`)
- Test: `crm/tests/test_rep_planning.py`, `crm/tests/test_rep_plan_api.py`

**Interfaces:**
- Produces: `ACTUAL_SOURCES["Visit"]` → `Event` rows with `event_category = "Event"`; `ACTUAL_SOURCES["Meeting"]` now excludes that category. `KIND_BY_DOCTYPE["Event"]` stays `"Meeting"` (Visit is declared first). Task 6 creates Events with `event_category = "Event"`.

- [ ] **Step 1: Write the failing matcher tests**

Append to `MatchItemsTest` in `crm/tests/test_rep_planning.py`:

```python
	def test_a_visit_item_is_fulfilled_by_a_visit_only(self):
		visit = actual(doctype="Event", name="EV-1", kind="Visit")
		self.assertEqual(match_items([item(activity_type="Visit")], [visit])["item-1"]["name"], "EV-1")
		meeting = actual(doctype="Event", name="EV-1", kind="Meeting")
		self.assertEqual(match_items([item(activity_type="Visit")], [meeting]), {})
```

Append a new class at the end of the same file:

```python
class EventKindsTest(IntegrationTestCase):
	"""One Event is emitted under exactly one kind, or a single visit could fulfil
	a Visit item and a Meeting item in the same run."""

	def tearDown(self):
		frappe.db.rollback()

	def _event(self, subject, category=None):
		return frappe.get_doc(
			{
				"doctype": "Event",
				"subject": subject,
				"starts_on": datetime(2026, 8, 12, 10, 0),
				"event_type": "Private",
				"event_category": category,
			}
		).insert()

	def test_visit_and_meeting_partition_events_by_category(self):
		visit = self._event("Site visit", "Event")
		meeting = self._event("Catch-up")
		window = (date(2026, 8, 10), date(2026, 8, 16))
		visits = {row["name"] for row in rep_planning._query_source("Visit", "Administrator", window)}
		meetings = {row["name"] for row in rep_planning._query_source("Meeting", "Administrator", window)}
		self.assertIn(visit.name, visits)
		self.assertNotIn(meeting.name, visits)
		self.assertIn(meeting.name, meetings)
		self.assertNotIn(visit.name, meetings)

	def test_the_reverse_map_still_names_meeting_for_an_event(self):
		self.assertEqual(rep_planning.KIND_BY_DOCTYPE["Event"], "Meeting")
```

Append to `crm/tests/test_rep_plan_api.py` (after the existing classes; `make_sales_user`, `REP`, `save_plan`, `get_plan`, `mark_fulfilled` are already imported there):

```python
from datetime import datetime, timedelta


def _this_monday() -> str:
	today = frappe.utils.getdate()
	return str(today - timedelta(days=today.weekday()))


class MarkFulfilledByKindTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Plan Rep")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.db.rollback()

	def _plan_with(self, activity_type: str) -> str:
		plan = save_plan(_this_monday(), [{"activity_type": activity_type, "planned_date": _this_monday()}])
		return plan["items"][0]["name"]

	def _event(self, category):
		return frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "x",
				"starts_on": datetime.now(),
				"event_type": "Private",
				"event_category": category,
			}
		).insert()

	def test_a_visit_item_accepts_a_visit_event_and_refuses_a_plain_one(self):
		item = self._plan_with("Visit")
		plain = self._event(None)
		with self.assertRaises(frappe.ValidationError):
			mark_fulfilled(item, "Event", plain.name)
		visit = self._event("Event")
		plan = mark_fulfilled(item, "Event", visit.name)
		self.assertEqual(plan["items"][0]["status"], "Done")

	def test_a_meeting_item_still_accepts_a_plain_event(self):
		item = self._plan_with("Meeting")
		plan = mark_fulfilled(item, "Event", self._event(None).name)
		self.assertEqual(plan["items"][0]["status"], "Done")
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.tests.test_rep_planning` and `--module crm.tests.test_rep_plan_api`
Expected: FAIL — the Visit item never matches (`KeyError: 'Visit'` from `ACTUAL_SOURCES`, or `save_plan` rejects the unknown Select value).

- [ ] **Step 3: Add the kind**

In `crm/fcrm/doctype/crm_rep_plan_item/crm_rep_plan_item.json`, change the `activity_type` field's options:

```json
"options": "Call\nMeeting\nTask\nEmail\nVisit",
```

In `crm/rep_planning.py`, replace the `"Meeting"` entry of `ACTUAL_SOURCES` with these two (Visit **before** Meeting, so the reverse map keeps naming Meeting for an Event):

```python
	"Visit": {
		# MBP's reps think in visits to plants and mines, not meetings. A visit is
		# a calendar event marked with the "Event" category; the calendar itself
		# sets no category, so nothing an existing site created changes kind.
		"doctype": "Event",
		"user_fields": ("owner",),
		"when_field": "starts_on",
		"when_is_activity_time": True,
		"filters": {"event_category": "Event"},
		"exclude": {"status": ("Cancelled",)},
	},
	"Meeting": {
		"doctype": "Event",
		"user_fields": ("owner",),
		"when_field": "starts_on",
		"when_is_activity_time": True,
		# a visit is not a meeting; without this one event could fulfil both kinds
		"exclude": {"status": ("Cancelled",), "event_category": ("Event",)},
	},
```

In `crm/api/rep_plan.py`, inside `mark_fulfilled`, replace the two lines

```python
		kind = KIND_BY_DOCTYPE[fulfilled_by_doctype]
		if not _query_source(kind, frappe.session.user, None, names=[fulfilled_by]):
```

with

```python
		# Event backs two kinds (Meeting, Visit) with different filters, so the
		# item's own kind decides which set of filters the record must satisfy;
		# the doctype-keyed fallback keeps cross-kind fulfilment as it was.
		item_kind = frappe.db.get_value("CRM Rep Plan Item", item, "activity_type")
		if ACTUAL_SOURCES.get(item_kind, {}).get("doctype") == fulfilled_by_doctype:
			kind = item_kind
		else:
			kind = KIND_BY_DOCTYPE[fulfilled_by_doctype]
		if not _query_source(kind, frappe.session.user, None, names=[fulfilled_by]):
```

- [ ] **Step 4: Migrate the test site and run the tests**

Run:
```
bench --site test_site migrate
bench --site test_site run-tests --module crm.tests.test_rep_planning
bench --site test_site run-tests --module crm.tests.test_rep_plan_api
```
Expected: PASS, including every pre-existing test in both modules.

- [ ] **Step 5: Commit**

```bash
git add crm/fcrm/doctype/crm_rep_plan_item/crm_rep_plan_item.json crm/rep_planning.py crm/api/rep_plan.py crm/tests/test_rep_planning.py crm/tests/test_rep_plan_api.py
git commit -m "feat: a Visit is an activity kind the matcher fulfils from the calendar

A visit is an Event in the \"Event\" category; Meeting now excludes that
category so one event is emitted under exactly one kind. mark_fulfilled
resolves the kind from the item, since Event backs two."
```

---

### Task 2: `Visit` in the Planner (G1, frontend)

**Files:**
- Modify: `frontend/src/pages/Planner.vue:384` (imports), `:679-688` (`typeIcon`), `:761` (options)

- [ ] **Step 1: Add the option, icon and import**

Next to the existing `import LucideCalendarClock from '~icons/lucide/calendar-clock'` add:

```js
import LucideMapPin from '~icons/lucide/map-pin'
```

In `itemDialogFields()` change the Select options to:

```js
      options: 'Call\nMeeting\nTask\nEmail\nVisit',
```

In `typeIcon` add the entry:

```js
      Visit: LucideMapPin,
```

- [ ] **Step 2: Check in the app**

Run `/dev-up`, open `/crm/planner`, click a day's "+", confirm **Visit** is offered, add one, save, and confirm it renders with a map-pin icon. Check in both themes.

- [ ] **Step 3: Run the frontend tests and commit**

Run: `cd /workspace/frontend && yarn test:run`
Expected: PASS (nothing here is unit-tested; the run guards against a broken import).

```bash
git add frontend/src/pages/Planner.vue
git commit -m "feat: plan a Visit from the Planner"
```

---

### Task 3: `Rescheduled` is a task status (G3)

**Files:**
- Modify: `crm/fcrm/doctype/crm_task/crm_task.json` (status options)
- Modify: `crm/fcrm/doctype/crm_task/crm_task.py:27` (the generated Literal)
- Modify: `frontend/src/components/Icons/TaskStatusIcon.vue`
- Test: `crm/fcrm/doctype/crm_task/test_crm_task.py`

- [ ] **Step 1: Write the failing test**

Append to `TestCRMTask` in `test_crm_task.py`:

```python
	def test_a_task_can_be_rescheduled(self):
		task = create_test_task(title="Site visit", status="Todo")
		task.status = "Rescheduled"
		task.closing_note = "Client moved it to next week"  # Task 4 requires this; harmless before
		task.save()
		self.assertEqual(frappe.db.get_value("CRM Task", task.name, "status"), "Rescheduled")
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task`
Expected: FAIL — `frappe.exceptions.ValidationError: Status cannot be "Rescheduled"`.

- [ ] **Step 3: Add the status**

In `crm_task.json`, the `status` field:

```json
"options": "Backlog\nTodo\nIn Progress\nRescheduled\nDone\nCanceled"
```

In `crm_task.py` line 27, the auto-generated type hint:

```python
		status: DF.Literal["Backlog", "Todo", "In Progress", "Rescheduled", "Done", "Canceled"]
```

In `TaskStatusIcon.vue`, add `PhArrowsClockwise` to the `@phosphor-icons/vue` import and to the map:

```js
import {
  PhArrowsClockwise,
  PhCheckCircle,
  PhCircle,
  PhCircleDashed,
  PhCircleHalf,
  PhXCircle,
} from '@phosphor-icons/vue'
```

```js
const GLYPH = {
  Backlog: PhCircleDashed,
  Todo: PhCircle,
  'In Progress': PhCircleHalf,
  // the client moved it: neither done nor dropped, and worth counting as its own thing
  Rescheduled: PhArrowsClockwise,
  Done: PhCheckCircle,
  Canceled: PhXCircle,
}
```

- [ ] **Step 4: Find any other hard-coded copy of the status list**

Run: `grep -rn "'In Progress', 'Done'" frontend/src crm --include=*.js --include=*.vue --include=*.py`
`frontend/src/utils/index.js:233` is a fallback overridden by meta — leave it. Any other literal list found must gain `'Rescheduled'` before `'Done'`; there should be none.

- [ ] **Step 5: Migrate, test, check the kanban**

Run:
```
bench --site test_site migrate
bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task
```
Expected: PASS. Then open `/crm/tasks` in kanban view: a **Rescheduled** column appears with the arrows glyph.

- [ ] **Step 6: Commit**

```bash
git add crm/fcrm/doctype/crm_task/ frontend/src/components/Icons/TaskStatusIcon.vue
git commit -m "feat: Rescheduled is a task status, distinct from Done and Canceled"
```

---

### Task 4: A note is required to close a task (G4)

**Files:**
- Modify: `crm/fcrm/doctype/crm_task/crm_task.json` (new field + `field_order`)
- Modify: `crm/fcrm/doctype/crm_task/crm_task.py` (`validate`)
- Modify: `crm/install.py` (`add_default_fields_layout` task layout; new helper `append_to_layout_column`)
- Create: `crm/patches/v1_0/add_closing_note_to_task_quick_entry.py`
- Modify: `crm/patches.txt`
- Test: `crm/fcrm/doctype/crm_task/test_crm_task.py`

**Interfaces:**
- Produces: `CRM Task.closing_note` (Small Text); `CLOSED_STATUSES = ("Done", "Canceled", "Rescheduled")` in `crm_task.py`; `crm.install.append_to_layout_column(layout: list, anchor: str, fieldname: str) -> bool` used again by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `TestCRMTask`:

```python
	def test_closing_without_a_note_is_refused(self):
		task = create_test_task(title="Call back", status="Todo")
		task.status = "Done"
		with self.assertRaises(frappe.MandatoryError):
			task.save()

	def test_closing_with_a_note_saves(self):
		task = create_test_task(title="Call back", status="Todo")
		task.status = "Canceled"
		task.closing_note = "Client no longer needs the part"
		task.save()
		self.assertEqual(frappe.db.get_value("CRM Task", task.name, "status"), "Canceled")

	def test_the_rule_is_about_the_transition_not_the_state(self):
		# created straight into Done (seeding, the matcher's fixtures): allowed
		task = create_test_task(title="Already done", status="Done")
		self.assertEqual(task.status, "Done")
		# editing something else on a closed task: allowed
		task.title = "Already done, renamed"
		task.save()
		# reopening needs nothing either
		task.status = "Todo"
		task.save()


class LayoutHelperTest(IntegrationTestCase):
	def test_append_to_layout_column_finds_the_anchor_in_tabs_or_sections(self):
		from crm.install import append_to_layout_column

		tabbed = [{"name": "t", "sections": [{"name": "s", "columns": [{"name": "c", "fields": ["status"]}]}]}]
		self.assertTrue(append_to_layout_column(tabbed, "status", "closing_note"))
		self.assertEqual(tabbed[0]["sections"][0]["columns"][0]["fields"], ["status", "closing_note"])
		self.assertFalse(append_to_layout_column(tabbed, "status", "closing_note"))  # idempotent

		flat = [{"name": "s", "columns": [{"name": "c", "fields": ["gender"]}]}]
		self.assertTrue(append_to_layout_column(flat, "gender", "birthday"))
		self.assertEqual(flat[0]["columns"][0]["fields"], ["gender", "birthday"])
		self.assertFalse(append_to_layout_column(flat, "missing", "x"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task`
Expected: FAIL — the first test saves without raising; `ImportError` for `append_to_layout_column`.

- [ ] **Step 3: Add the field**

In `crm_task.json`, after the `description` entry in `fields` add:

```json
  {
   "fieldname": "closing_note",
   "fieldtype": "Small Text",
   "label": "Closing Note",
   "description": "Required when a task is marked Done, Canceled or Rescheduled"
  },
```

and append `"closing_note"` to the end of `field_order` (after `"description"`).

- [ ] **Step 4: Enforce it**

In `crm_task.py`, add at module level (after the imports):

```python
# A closed task must say why. The old rep app refused to close a call without a
# comment and that discipline is what made its history worth reading; losing it
# would be the first regression reps notice.
CLOSED_STATUSES = ("Done", "Canceled", "Rescheduled")
```

and in the class, make `validate` start with the new check:

```python
	def validate(self):
		self.require_closing_note()
		if self.is_new() or not self.assigned_to:
			return

		if self.get_doc_before_save().assigned_to != self.assigned_to:
			self.unassign_from_previous_user(self.get_doc_before_save().assigned_to)
			self.assign_to()

	def require_closing_note(self):
		"""On the transition into a closed status only. A task created already closed
		(seeding, fixtures) or edited while closed is not the moment the rule is for."""
		if self.status not in CLOSED_STATUSES or self.is_new():
			return
		before = self.get_doc_before_save()
		if before and before.status == self.status:
			return
		if not (self.closing_note or "").strip():
			frappe.throw(
				_("Add a closing note before marking this task {0}.").format(_(self.status)),
				frappe.MandatoryError,
			)
```

Add `from frappe import _` to the imports.

- [ ] **Step 5: Put the field on the quick-entry form**

In `crm/install.py`, add the helper near `add_default_fields_layout`:

```python
def append_to_layout_column(layout: list, anchor: str, fieldname: str) -> bool:
	"""Add ``fieldname`` after ``anchor`` in whichever column holds it.

	Layouts come in two shapes -- tabs holding sections, or sections at the top
	level -- and a patch must not care which. Returns False when the anchor is
	absent or the field is already there, so a patch can run twice safely."""
	nodes = list(layout)
	while nodes:
		node = nodes.pop(0)
		for column in node.get("columns", []):
			fields = column.get("fields", [])
			if fieldname in fields:
				return False
			if anchor in fields:
				fields.insert(fields.index(anchor) + 1, fieldname)
				return True
		nodes.extend(node.get("sections", []))
	return False
```

In `add_default_fields_layout`, change the `"CRM Task-Quick Entry"` layout string so its second column reads `["assigned_to","status","closing_note"]`:

```python
		"CRM Task-Quick Entry": {
			"doctype": "CRM Task",
			"layout": '[{"name":"first_tab","sections":[{"name":"details_section","columns":[{"name":"column_X9sG","fields":["title","description"]}]},{"name":"assignment_section","columns":[{"name":"column_9XjK","fields":["priority","due_date"]},{"name":"column_7s8n","fields":["assigned_to","status","closing_note"]}],"hideBorder":true}]}]',
		},
```

Create `crm/patches/v1_0/add_closing_note_to_task_quick_entry.py`:

```python
import json

import frappe

from crm.install import append_to_layout_column

LAYOUT = "CRM Task-Quick Entry"


def execute():
	"""Existing sites keep their stored quick-entry layout; put the new field where
	the status is. Fresh installs get it from add_default_fields_layout."""
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	layout = json.loads(frappe.db.get_value("CRM Fields Layout", LAYOUT, "layout") or "[]")
	if append_to_layout_column(layout, "status", "closing_note"):
		frappe.db.set_value("CRM Fields Layout", LAYOUT, "layout", json.dumps(layout))
```

Append to `crm/patches.txt`:

```
crm.patches.v1_0.add_closing_note_to_task_quick_entry
```

- [ ] **Step 6: Migrate, test, check the modal**

Run:
```
bench --site test_site migrate
bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task
bench --site test_site run-tests --module crm.tests.test_rep_planning
```
Expected: PASS — including the matcher tests that create tasks directly as Done.

Then open `/crm/tasks`, open a Todo task, set status **Done** with an empty note, Save: the modal shows *Add a closing note before marking this task Done.* Fill the note, Save: closes.

- [ ] **Step 7: Commit**

```bash
git add crm/fcrm/doctype/crm_task/ crm/install.py crm/patches/v1_0/add_closing_note_to_task_quick_entry.py crm/patches.txt
git commit -m "feat: a task cannot be closed without a closing note

Enforced in validate on the transition into Done, Canceled or Rescheduled
-- not on insert, so seeding and fixtures still create closed tasks. The
field joins the quick-entry layout on fresh and existing sites."
```

---

### Task 5: Task history is recorded and shown (G7)

**Files:**
- Modify: `crm/fcrm/doctype/crm_task/crm_task.json` (`track_changes`)
- Create: `crm/api/task.py`
- Modify: `frontend/src/components/Modals/DoctypeModal.vue:50-57`
- Test: `crm/fcrm/doctype/crm_task/test_crm_task.py`

**Interfaces:**
- Produces: `crm.api.task.get_history(name) -> list[dict]` — newest first, each `{"creation", "owner", "changes": [{"field", "label", "old", "new"}]}`.

- [ ] **Step 1: Write the failing test**

Append to `TestCRMTask`:

```python
	def test_history_lists_each_change_with_the_note_that_came_with_it(self):
		from crm.api.task import get_history

		task = create_test_task(title="Visit 4D Union", status="Todo")
		task.status = "Rescheduled"
		task.closing_note = "Client asked for the 21st"
		task.save()
		history = get_history(task.name)
		self.assertGreaterEqual(len(history), 1)
		latest = history[0]
		fields = {change["field"]: change for change in latest["changes"]}
		self.assertEqual(fields["status"]["old"], "Todo")
		self.assertEqual(fields["status"]["new"], "Rescheduled")
		self.assertEqual(fields["closing_note"]["new"], "Client asked for the 21st")
		self.assertEqual(fields["status"]["label"], "Status")
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task`
Expected: FAIL — `ModuleNotFoundError: crm.api.task`.

- [ ] **Step 3: Record and serve the history**

In `crm_task.json`, add at the top level (next to `"engine"` or `"editable_grid"`):

```json
 "track_changes": 1,
```

Create `crm/api/task.py`:

```python
import json

import frappe
from frappe import _


@frappe.whitelist()
def get_history(name: str) -> list[dict]:
	"""What changed on a task, and who did it, newest first.

	The old rep app showed the edit trail inside the activity dialog beside the
	note that came with each change; ``track_changes`` already records exactly
	that as Version rows, so this only reshapes them."""
	frappe.has_permission("CRM Task", "read", doc=name, throw=True)
	labels = {f.fieldname: f.label for f in frappe.get_meta("CRM Task").fields}
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "CRM Task", "docname": name},
		fields=["creation", "owner", "data"],
		order_by="creation desc",
	)
	history = []
	for row in rows:
		data = json.loads(row.data or "{}")
		changes = [
			{"field": field, "label": _(labels.get(field) or field), "old": old, "new": new}
			for field, old, new in data.get("changed", [])
			if old != new
		]
		if changes:
			history.append({"creation": row.creation, "owner": row.owner, "changes": changes})
	return history
```

- [ ] **Step 4: Show it in the task modal**

In `DoctypeModal.vue`, directly after the `<FieldLayout ... />` element (before `<ErrorMessage>`), add:

```vue
          <div v-if="doctype === 'CRM Task' && docname" class="mt-6">
            <div class="mb-2 text-sm font-medium text-ink-gray-7">
              {{ __('History') }}
            </div>
            <div
              v-if="history.data?.length"
              class="max-h-48 space-y-2 overflow-y-auto text-sm"
            >
              <div v-for="(entry, i) in history.data" :key="i">
                <div class="text-ink-gray-5">
                  {{ entry.owner }} · {{ formatDate(entry.creation) }}
                </div>
                <div v-for="change in entry.changes" :key="change.field" class="text-ink-gray-8">
                  <span class="font-medium">{{ change.label }}</span>:
                  <span v-if="change.old" class="line-through text-ink-gray-5">{{ change.old }}</span>
                  {{ change.new }}
                </div>
              </div>
            </div>
            <div v-else class="text-sm text-ink-gray-5">
              {{ __('No history for this task yet.') }}
            </div>
          </div>
```

In `<script setup>`, after the existing `createResource` imports and the `props` definition, add:

```js
const history = createResource({
  url: 'crm.api.task.get_history',
  params: { name: props.docname },
  auto: props.doctype === 'CRM Task' && !!props.docname,
})

function formatDate(value) {
  return new Date(value).toLocaleString()
}
```

If `createResource` is not already imported from `frappe-ui` in this file, add it to that import.

- [ ] **Step 5: Migrate, test, check the modal**

Run:
```
bench --site test_site migrate
bench --site test_site run-tests --module crm.fcrm.doctype.crm_task.test_crm_task
```
Expected: PASS. Then reschedule a task in `/crm/tasks` with a note and reopen it: the History block lists the status change and the note, with the actor and time. Check both themes; the struck-through old value must stay legible.

- [ ] **Step 6: Commit**

```bash
git add crm/fcrm/doctype/crm_task/crm_task.json crm/api/task.py frontend/src/components/Modals/DoctypeModal.vue crm/fcrm/doctype/crm_task/test_crm_task.py
git commit -m "feat: a task's edit history is recorded and shown in its dialog"
```

---

### Task 6: Log an unplanned visit (G2)

**Files:**
- Modify: `crm/api/rep_plan.py`
- Modify: `frontend/src/pages/Planner.vue` (header button)
- Test: `crm/tests/test_rep_plan_api.py`

**Interfaces:**
- Consumes: `week_of` from `crm.rep_planning`; `_plan_for`, `get_plan`, `REFERENCE_DOCTYPES` in `rep_plan.py`; `ACTUAL_SOURCES["Visit"]` from Task 1.
- Produces: `crm.api.rep_plan.log_unplanned_visit(organization, note, when=None, reference_doctype=None, reference_docname=None)` → the `get_plan` payload for the week of the visit.

- [ ] **Step 1: Write the failing tests**

Append to `crm/tests/test_rep_plan_api.py`:

```python
from crm.api.rep_plan import log_unplanned_visit


class UnplannedVisitTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Plan Rep")
		self.org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": "4D Union Section"}).insert()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.db.rollback()

	def test_logs_a_done_visit_the_matcher_will_leave_alone(self):
		plan = log_unplanned_visit(self.org.name, "Called to site for a breakdown on the 200mm valve")
		item = plan["items"][0]
		self.assertEqual(item["activity_type"], "Visit")
		self.assertEqual(item["status"], "Done")
		self.assertEqual(item["manual_override"], 1)
		self.assertEqual(item["fulfilled_by_doctype"], "Event")
		event = frappe.get_doc("Event", item["fulfilled_by"])
		self.assertEqual(event.event_category, "Event")
		self.assertEqual(event.status, "Completed")
		self.assertEqual(event.owner, REP)
		self.assertIn(self.org.name, [p.reference_docname for p in event.event_participants])

	def test_a_note_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(self.org.name, "   ")

	def test_an_unknown_organization_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			log_unplanned_visit("Nobody Ltd", "x")

	def test_lands_in_the_week_of_the_visit_not_today(self):
		when = frappe.utils.get_datetime(_this_monday()) - timedelta(days=7)
		plan = log_unplanned_visit(self.org.name, "last week", when=str(when))
		self.assertEqual(plan["week_start"], str(when.date()))
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.tests.test_rep_plan_api`
Expected: FAIL — `ImportError: cannot import name 'log_unplanned_visit'`.

- [ ] **Step 3: Implement the endpoint**

In `crm/api/rep_plan.py`, extend the `crm.rep_planning` import to include `week_of`:

```python
from crm.rep_planning import ACTUAL_SOURCES, KIND_BY_DOCTYPE, MATCH_HORIZON_WEEKS, _query_source, week_of
```

and add after `propose_week`:

```python
@frappe.whitelist()
@sales_user_only
def log_unplanned_visit(
	organization: str,
	note: str,
	when: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
):
	"""Record a visit that was never planned -- a rep called to site for a breakdown --
	as already done, in one step.

	Creates the calendar Event the matcher would have looked for and a plan item that
	is fulfilled by it and flagged ``manual_override``, so the daily job never
	reconsiders it. The rep's word is the record here, exactly as in ``mark_fulfilled``.
	"""
	if not (note or "").strip():
		frappe.throw(_("Say what happened on the visit."), frappe.ValidationError)
	if not frappe.db.exists("CRM Organization", organization):
		frappe.throw(_("Organization {0} not found.").format(organization), frappe.DoesNotExistError)
	if reference_doctype and reference_doctype not in REFERENCE_DOCTYPES:
		frappe.throw(_("{0} cannot be the subject of a visit.").format(reference_doctype))

	when_dt = frappe.utils.get_datetime(when) if when else frappe.utils.now_datetime()
	monday, _sunday = week_of(when_dt.date())
	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	if monday < horizon:
		frappe.throw(_("Visits older than {0} weeks can no longer be logged.").format(MATCH_HORIZON_WEEKS))

	event = frappe.get_doc(
		{
			"doctype": "Event",
			"subject": _("Visit: {0}").format(organization),
			"starts_on": when_dt,
			"ends_on": when_dt + timedelta(hours=1),
			"event_type": "Private",
			# the category is what makes this a Visit to the matcher, not a Meeting
			"event_category": "Event",
			"status": "Completed",
			"description": note,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"event_participants": [{"reference_doctype": "CRM Organization", "reference_docname": organization}],
		}
	).insert(ignore_permissions=True)

	user = frappe.session.user
	for attempt in range(2):
		plan = _plan_for(user, str(monday))
		plan.append(
			"items",
			{
				"activity_type": "Visit",
				"planned_date": when_dt.date(),
				"note": note,
				"reference_doctype": reference_doctype,
				"reference_docname": reference_docname,
				"status": "Done",
				"manual_override": 1,
				"fulfilled_by_doctype": "Event",
				"fulfilled_by": event.name,
			},
		)
		frappe.db.savepoint("log_visit")
		try:
			plan.save(ignore_permissions=True)
			break
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			# same race as save_plan: two first saves of one week, the index decides
			frappe.db.rollback(save_point="log_visit")
			if attempt:
				raise
	return get_plan(str(monday), user)
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.tests.test_rep_plan_api`
Expected: PASS. If `get_plan` raises a permission error, the test is not running as `REP` — check `frappe.set_user(REP)` in `setUp`.

- [ ] **Step 5: Add the button**

In `Planner.vue`, in the `#right-header` template, before the "Propose my week" button:

```vue
      <Button
        v-if="isOwnPlan"
        :label="__('Log a visit')"
        :disabled="logging"
        :loading="logging"
        @click="logVisit"
      >
        <template #prefix>
          <LucideMapPin class="size-4" />
        </template>
      </Button>
```

In `<script setup>`, near `saving`/`proposing`, add:

```js
const logging = ref(false)

/* An unplanned visit -- "called to site for a breakdown" in MBP's words --
   is recorded as already done. The server creates the calendar event and the
   fulfilled item; we only collect the facts. */
async function logVisit() {
  const data = await renderFieldLayoutDialog({
    title: __('Log an unplanned visit'),
    size: 'md',
    fields: [
      {
        fieldname: 'organization',
        fieldtype: 'Link',
        label: __('Organization'),
        options: 'CRM Organization',
      },
      { fieldname: 'when', fieldtype: 'Datetime', label: __('When') },
      { fieldname: 'note', fieldtype: 'Small Text', label: __('What happened') },
      {
        fieldname: 'reference_doctype',
        fieldtype: 'Select',
        label: __('Related to'),
        options: [
          { label: '', value: '' },
          { label: __('Deal'), value: 'CRM Deal' },
          { label: __('Lead'), value: 'CRM Lead' },
        ],
      },
      {
        fieldname: 'reference_docname',
        fieldtype: 'Dynamic Link',
        label: __('Record'),
        options: 'reference_doctype',
      },
    ],
    required: ['organization', 'note'],
    submitLabel: __('Log visit'),
    cancelLabel: __('Cancel'),
  })
  if (!data) return
  logging.value = true
  try {
    const plan = await call('crm.api.rep_plan.log_unplanned_visit', {
      organization: data.organization,
      note: data.note,
      when: data.when || undefined,
      reference_doctype: data.reference_doctype || undefined,
      reference_docname: data.reference_doctype ? data.reference_docname || undefined : undefined,
    })
    // The visit may belong to a different week than the one on screen; only
    // adopt the payload when it is this week, otherwise just say where it went.
    if (plan.week_start === weekStart.value) {
      adoptServerPlan(plan)
      loadReferenceTitles(plan.items)
    }
    toast.success(__('Visit logged for the week of {0}', [plan.week_start]))
  } catch (error) {
    toast.error(errorText(error))
  } finally {
    logging.value = false
  }
}
```

`ref`, `call`, `toast`, `renderFieldLayoutDialog`, `adoptServerPlan`, `loadReferenceTitles`, `errorText`, `weekStart` and `LucideMapPin` (Task 2) all exist in the file already.

- [ ] **Step 6: Check in the app and commit**

Open `/crm/planner`, click **Log a visit**, pick an organization, write a note, submit: a Done Visit item appears on today's column with the map-pin icon and a green tick; the Calendar page shows the event. Then:

```bash
git add crm/api/rep_plan.py frontend/src/pages/Planner.vue crm/tests/test_rep_plan_api.py
git commit -m "feat: log an unplanned visit as already done

Creates the calendar event the matcher would look for and a fulfilled,
manually-overridden plan item in one step -- a rep called to site for a
breakdown records it after the fact."
```

---

### Task 7: Lead form parity — birthday, contact type, provinces (G9)

**Files:**
- Modify: `crm/fcrm/doctype/crm_lead/crm_lead.json`
- Modify: `crm/install.py` (`ensure_sa_provinces`, `after_install`, lead quick-entry layout)
- Create: `crm/patches/v1_0/add_person_fields_to_lead_quick_entry.py`, `crm/patches/v1_0/ensure_sa_provinces.py`
- Modify: `crm/patches.txt`
- Test: `crm/tests/test_lead_person_fields.py` (create)

**Interfaces:**
- Produces: `CRM Lead.birthday` (Date), `CRM Lead.contact_type` (Select); `crm.install.SA_PROVINCES`, `crm.install.ensure_sa_provinces()`. Province is the existing `territory` Link, now seeded.

- [ ] **Step 1: Write the failing tests**

Create `crm/tests/test_lead_person_fields.py`:

```python
"""The three fields the old rep app's New Lead form captured and CRM Lead did not."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.install import SA_PROVINCES, ensure_sa_provinces


class LeadPersonFieldsTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_birthday_and_contact_type_are_stored(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Piet",
				"last_name": "Fourie",
				"birthday": "1979-03-14",
				"contact_type": "Maintenance",
			}
		).insert()
		self.assertEqual(str(lead.birthday), "1979-03-14")
		self.assertEqual(lead.contact_type, "Maintenance")

	def test_an_unknown_contact_type_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "CRM Lead", "first_name": "X", "contact_type": "Astronaut"}).insert()

	def test_provinces_exist_as_territories_and_seeding_is_idempotent(self):
		ensure_sa_provinces()
		ensure_sa_provinces()
		for province in SA_PROVINCES:
			self.assertTrue(frappe.db.exists("CRM Territory", province), province)
		self.assertEqual(len(SA_PROVINCES), 9)
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.tests.test_lead_person_fields`
Expected: FAIL — `ImportError: cannot import name 'SA_PROVINCES'`; the insert ignores unknown fields so the first assertion fails on `birthday`.

- [ ] **Step 3: Add the fields**

In `crm_lead.json`, after the `job_title` entry in `fields`, add:

```json
  {
   "fieldname": "birthday",
   "fieldtype": "Date",
   "label": "Birthday"
  },
  {
   "fieldname": "contact_type",
   "fieldtype": "Select",
   "label": "Contact Type",
   "options": "\nBuyer\nEngineer\nMaintenance\nProcurement\nManagement\nOther"
  },
```

In `field_order`, insert `"birthday", "contact_type"` immediately after `"job_title"`.

The contact-type values are a starting set; MBP's own list was not visible in the screenshots. They are a Select so an admin can edit them in Customize Form without a release.

- [ ] **Step 4: Seed the provinces and update the layouts**

In `crm/install.py`, add near `ensure_zar_currency`:

```python
SA_PROVINCES = (
	"Eastern Cape",
	"Free State",
	"Gauteng",
	"KwaZulu-Natal",
	"Limpopo",
	"Mpumalanga",
	"North West",
	"Northern Cape",
	"Western Cape",
)


def ensure_sa_provinces():
	"""The old rep app's lead form has a Province picker; here that is Territory.
	Idempotent, called from after_install and the patch for the same reason as
	ensure_zar_currency: patches are marked executed, never run, on a fresh install."""
	for province in SA_PROVINCES:
		if not frappe.db.exists("CRM Territory", province):
			frappe.get_doc({"doctype": "CRM Territory", "territory_name": province}).insert(ignore_permissions=True)
```

In `after_install`, call `ensure_sa_provinces()` on the line after `ensure_zar_currency()`.

In `add_default_fields_layout`, change the `"CRM Lead-Quick Entry"` layout so the person section's columns read:

```
{"name": "column_5jrk", "fields": ["salutation", "email"]}, {"name": "column_5CPV", "fields": ["first_name", "mobile_no", "contact_type"]}, {"name": "column_gXOy", "fields": ["last_name", "gender", "birthday"]}
```

(the rest of that string is unchanged).

Create `crm/patches/v1_0/add_person_fields_to_lead_quick_entry.py`:

```python
import json

import frappe

from crm.install import append_to_layout_column

LAYOUT = "CRM Lead-Quick Entry"


def execute():
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	layout = json.loads(frappe.db.get_value("CRM Fields Layout", LAYOUT, "layout") or "[]")
	changed = append_to_layout_column(layout, "gender", "birthday")
	changed = append_to_layout_column(layout, "mobile_no", "contact_type") or changed
	if changed:
		frappe.db.set_value("CRM Fields Layout", LAYOUT, "layout", json.dumps(layout))
```

Create `crm/patches/v1_0/ensure_sa_provinces.py`:

```python
from crm.install import ensure_sa_provinces


def execute():
	ensure_sa_provinces()
```

Append to `crm/patches.txt`:

```
crm.patches.v1_0.add_person_fields_to_lead_quick_entry
crm.patches.v1_0.ensure_sa_provinces
```

- [ ] **Step 5: Migrate, test, check the form**

Run:
```
bench --site test_site migrate
bench --site test_site run-tests --module crm.tests.test_lead_person_fields
```
Expected: PASS. Then `/crm/leads` → Create: the form shows **Contact Type** under mobile and **Birthday** under gender; **Territory** offers the nine provinces.

- [ ] **Step 6: Commit**

```bash
git add crm/fcrm/doctype/crm_lead/crm_lead.json crm/install.py crm/patches/v1_0/add_person_fields_to_lead_quick_entry.py crm/patches/v1_0/ensure_sa_provinces.py crm/patches.txt crm/tests/test_lead_person_fields.py
git commit -m "feat: leads carry a birthday and contact type; provinces are territories"
```

---

### Task 8: Find an organization by customer code (G6)

Read the spec's G6 before starting — it explains why the missing-column case must be *surfaced*, not silent, and why the probe is a one-line null check.

**Files:**
- Create: `crm/api/organization.py`
- Modify: `frontend/src/pages/Organizations.vue:6-16` (right header)
- Test: `crm/tests/test_organization_api.py` (create)

**Interfaces:**
- Consumes: the `acumatica_id` custom field created by `ensure_custom_fields()` (import plan, Task 1 / Prerequisite 1).
- Produces: `crm.api.organization.find_by_code(code) -> list[{"name", "acumatica_id"}]`, prefix match, at most 20 rows, ordered by code.

- [ ] **Step 1: Write the failing tests**

Create `crm/tests/test_organization_api.py`:

```python
"""Customer-code search. Reps know their accounts as C-IMP003E, not by name."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.organization import find_by_code
from crm.integrations.acumatica.install import ensure_custom_fields


class FindByCodeTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()

	def setUp(self):
		super().setUp()
		for code, name in (("C-IMP003E", "Impala - Shaft 10"), ("C-IMP003F", "Impala - Shaft 11"), ("C-SIB001", "Sibanye")):
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": name, "acumatica_id": code}).insert()

	def tearDown(self):
		frappe.db.rollback()

	def test_prefix_match_ordered_by_code(self):
		rows = find_by_code("c-imp003")
		self.assertEqual([r["acumatica_id"] for r in rows], ["C-IMP003E", "C-IMP003F"])
		self.assertEqual(rows[0]["name"], "Impala - Shaft 10")

	def test_no_match_is_an_empty_list_not_an_error(self):
		self.assertEqual(find_by_code("C-NOPE"), [])

	def test_a_blank_code_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			find_by_code("  ")

	def test_a_site_without_the_field_is_told_so_rather_than_shown_nothing(self):
		meta = frappe.get_meta("CRM Organization")
		with patch.object(meta, "get_field", return_value=None), patch("frappe.get_meta", return_value=meta):
			with self.assertRaisesRegex(frappe.ValidationError, "not installed"):
				find_by_code("C-IMP003E")
```

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site run-tests --module crm.tests.test_organization_api`
Expected: FAIL — `ModuleNotFoundError: crm.api.organization`.

- [ ] **Step 3: Implement**

Create `crm/api/organization.py`:

```python
import frappe
from frappe import _

MAX_MATCHES = 20


@frappe.whitelist()
def find_by_code(code: str) -> list[dict]:
	"""Organizations whose Acumatica customer code starts with ``code``.

	``acumatica_id`` is a custom field that only exists once
	``ensure_custom_fields()`` has run. As sync bookkeeping its absence was
	invisible; as a search key it would be *silent* -- an empty result set that
	reads as "search is broken" and gets debugged as one. So the absence is the
	first thing checked, and it is reported, not swallowed."""
	frappe.has_permission("CRM Organization", "read", throw=True)
	if not frappe.get_meta("CRM Organization").get_field("acumatica_id"):
		frappe.throw(
			_(
				"Searching by customer code needs the Acumatica ID field, which is not installed on this site. "
				"Run crm.integrations.acumatica.install.ensure_custom_fields."
			),
			frappe.ValidationError,
			title=_("Not set up"),
		)
	code = (code or "").strip()
	if not code:
		frappe.throw(_("Enter a customer code."), frappe.ValidationError)
	return frappe.get_all(
		"CRM Organization",
		filters={"acumatica_id": ("like", f"{code}%")},
		fields=["name", "acumatica_id"],
		order_by="acumatica_id asc",
		limit=MAX_MATCHES,
	)
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.tests.test_organization_api`
Expected: PASS.

- [ ] **Step 5: Add the search box**

In `Organizations.vue`, inside `<template #right-header>` before `<CustomActions`, add:

```vue
      <!-- MBP's reps identify an account by its Acumatica code (C-IMP003E),
           which is what both screens of their old app searched on. -->
      <div class="flex items-center gap-1">
        <FormControl
          v-model="codeQuery"
          type="text"
          size="sm"
          :placeholder="__('Customer code')"
          class="w-36"
          @keydown.enter="findByCode"
        />
        <Button
          variant="subtle"
          :label="__('Find')"
          :loading="findingCode"
          @click="findByCode"
        />
      </div>
```

In `<script setup>`, add (with `ref` from `vue`, `call`, `toast`, `FormControl` from `frappe-ui`, and `useRouter` already available or added to the imports):

```js
const codeQuery = ref('')
const findingCode = ref(false)

async function findByCode() {
  if (!codeQuery.value.trim() || findingCode.value) return
  findingCode.value = true
  try {
    const rows = await call('crm.api.organization.find_by_code', {
      code: codeQuery.value,
    })
    if (!rows.length) {
      toast.warning(__('No organization has a code starting with {0}', [codeQuery.value]))
      return
    }
    // One exact hit opens it; several narrow the list to the prefix instead.
    const exact = rows.find(
      (r) => r.acumatica_id.toLowerCase() === codeQuery.value.trim().toLowerCase(),
    )
    if (exact || rows.length === 1) {
      router.push({
        name: 'Organization',
        params: { organizationId: (exact || rows[0]).name },
      })
      return
    }
    organizations.value.params.filters = {
      ...(organizations.value.params.filters || {}),
      acumatica_id: ['like', `${codeQuery.value.trim()}%`],
    }
    organizations.value.reload()
  } catch (error) {
    // The missing-field case arrives here as a server message; it must be read, not hidden.
    toast.error(error?.messages?.[0] || __('Could not search by code'))
  } finally {
    findingCode.value = false
  }
}
```

If `router` is not already defined in the file, add `const router = useRouter()` with `import { useRouter } from 'vue-router'`.

- [ ] **Step 6: Check in the app and commit**

On the dev site (which has the custom fields from the import plan's Task 1, or from running `ensure_custom_fields`), set `acumatica_id` on two organizations via the desk, then on `/crm/organizations` type a code and press Enter: an exact code opens the organization; a prefix filters the list. To see the surfaced error, temporarily delete the `acumatica_id` Custom Field on the dev site and search: the toast reads *…not installed on this site…* — then recreate it with `bench --site <dev site> execute crm.integrations.acumatica.install.ensure_custom_fields`.

```bash
git add crm/api/organization.py frontend/src/pages/Organizations.vue crm/tests/test_organization_api.py
git commit -m "feat: find an organization by its Acumatica customer code

A site without the field is told so; an empty result set would read as a
broken search and be debugged in the wrong place."
```

---

### Task 9: Cancellations per rep (G8)

**Files:**
- Modify: `crm/api/dashboard.py` (`plan_adherence`, new `activity_cancellations`)
- Modify: `crm/api/reports.py` (`plan_adherence_by_rep` columns)
- Test: `crm/tests/test_reports.py`

**Interfaces:**
- Produces: `activity_cancellations(from_date, to_date, user=None, group_by_user=False) -> list[dict]` with `user` (when grouped) and `cancelled`; every `plan_adherence` row gains a `cancelled` key.

- [ ] **Step 1: Write the failing test**

Append to `crm/tests/test_reports.py` (the module already imports `frappe`, `IntegrationTestCase` and `get_report`; add `from datetime import timedelta` and `from crm.api.dashboard import activity_cancellations, plan_adherence` if not present):

```python
class CancellationsTest(IntegrationTestCase):
	USER = "cancel-rep@crmtest.test"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Cancel Rep", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("Sales User")

	def tearDown(self):
		frappe.db.rollback()

	def _task(self, status):
		task = frappe.get_doc({"doctype": "CRM Task", "title": "t", "status": "Todo", "assigned_to": self.USER}).insert()
		task.status = status
		task.closing_note = "n"
		task.save()
		return task

	def test_cancelled_tasks_and_events_are_counted_per_rep_and_reported(self):
		self._task("Canceled")
		self._task("Canceled")
		self._task("Done")
		frappe.get_doc(
			{"doctype": "Event", "subject": "e", "starts_on": frappe.utils.now_datetime(), "event_type": "Private", "status": "Cancelled", "owner": self.USER}
		).insert(ignore_permissions=True)
		today = frappe.utils.nowdate()
		rows = activity_cancellations(today, today, user=self.USER)
		self.assertEqual(rows[0]["cancelled"], 3)

		adherence = plan_adherence(today, today, user=self.USER)
		self.assertEqual(adherence[0]["cancelled"], 3)
		self.assertEqual(adherence[0]["planned"], 0)  # unchanged: no plan items exist

		report = get_report("plan_adherence_by_rep", today, today, self.USER)
		self.assertIn({"key": "cancelled", "label": "Cancelled", "type": "number"}, report["columns"])
```

Note: `frappe.get_all` cannot set `owner` on insert in every version; if the Event test row comes back owned by Administrator, replace the insert with `frappe.set_user(self.USER)` around it (and `addCleanup(frappe.set_user, "Administrator")`).

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site run-tests --module crm.tests.test_reports`
Expected: FAIL — `ImportError: cannot import name 'activity_cancellations'`.

- [ ] **Step 3: Implement**

In `crm/api/dashboard.py`, add before `plan_adherence`:

```python
def activity_cancellations(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	group_by_user: bool = False,
):
	"""Tasks cancelled and calendar events cancelled in the period, per rep.

	The old rep app's admin view charted cancellations per user next to
	completions; the matcher never counts them because a cancellation fulfils
	nothing. Tasks are dated by ``modified`` for the same reason the matcher is
	(no completion timestamp exists); events by when they were to happen."""
	Task = DocType("CRM Task")
	Event = DocType("Event")
	end = add_days(to_date, 1)

	tasks = (
		frappe.qb.from_(Task)
		.where(Task.status == "Canceled")
		.where((Task.modified >= from_date) & (Task.modified < end))
		.select(Task.assigned_to.as_("user"), Count(Task.name).as_("cancelled"))
		.groupby(Task.assigned_to)
	)
	events = (
		frappe.qb.from_(Event)
		.where(Event.status == "Cancelled")
		.where((Event.starts_on >= from_date) & (Event.starts_on < end))
		.select(Event.owner.as_("user"), Count(Event.name).as_("cancelled"))
		.groupby(Event.owner)
	)
	if user:
		tasks = tasks.where(Task.assigned_to == user)
		events = events.where(Event.owner == user)
	else:
		reps = visible_reps()
		if reps is not None:
			tasks = tasks.where(Task.assigned_to.isin(reps))
			events = events.where(Event.owner.isin(reps))

	totals: dict[str, int] = {}
	for row in tasks.run(as_dict=True) + events.run(as_dict=True):
		totals[row.user] = totals.get(row.user, 0) + (row.cancelled or 0)

	if group_by_user:
		return [frappe._dict({"user": u, "cancelled": n}) for u, n in sorted(totals.items())]
	return [frappe._dict({"cancelled": sum(totals.values())})]
```

Then at the end of `plan_adherence`, before `return rows`, merge the counts in:

```python
	cancellations = activity_cancellations(from_date, to_date, user, group_by_user)
	if group_by_user:
		by_user = {row["user"]: row["cancelled"] for row in cancellations}
		seen = {row["user"] for row in rows}
		for row in rows:
			row["cancelled"] = by_user.get(row["user"], 0)
		# a rep with cancellations and no plan items still has a row to show them on
		for u, n in by_user.items():
			if u not in seen:
				rows.append(frappe._dict({"user": u, "planned": 0, "done": 0, "missed": 0, "adherence": 0, "cancelled": n}))
	else:
		rows[0]["cancelled"] = cancellations[0]["cancelled"]
```

In `crm/api/reports.py`, in the `plan_adherence_by_rep` entry, add the column after `missed`:

```python
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
```

- [ ] **Step 4: Run the reporting tests**

Run:
```
bench --site test_site run-tests --module crm.tests.test_reports
bench --site test_site run-tests --module crm.tests.test_dashboard
bench --site test_site run-tests --module crm.tests.test_quota
```
Expected: PASS — the pre-existing adherence assertions are unchanged because `planned`/`done`/`missed` are untouched.

- [ ] **Step 5: Commit**

```bash
git add crm/api/dashboard.py crm/api/reports.py crm/tests/test_reports.py
git commit -m "feat: cancellations per rep beside plan adherence"
```

---

### Task 10: Client Reliability (G5)

**Files:**
- Modify: `crm/api/dashboard.py` (new `client_reliability`)
- Modify: `crm/api/reports.py` (new `client_reliability` report)
- Test: `crm/tests/test_reports.py`

**Interfaces:**
- Produces: `client_reliability(from_date, to_date, user=None) -> list[dict]` rows `{organization, total, done, rescheduled, cancelled}` sorted by `rescheduled + cancelled` desc then name; report key `client_reliability`.

- [ ] **Step 1: Write the failing test**

Append to `crm/tests/test_reports.py` (add `from crm.api.dashboard import client_reliability`):

```python
class ClientReliabilityTest(IntegrationTestCase):
	USER = "reliab-rep@crmtest.test"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Reliab Rep", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("Sales User")
		self.flaky = frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Flaky Mine"}).insert()
		self.solid = frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Solid Works"}).insert()
		self.flaky_deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.flaky.name, "deal_owner": self.USER}).insert()
		self.solid_deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.solid.name, "deal_owner": self.USER}).insert()

	def tearDown(self):
		frappe.db.rollback()

	def _task(self, deal, status):
		task = frappe.get_doc(
			{"doctype": "CRM Task", "title": "t", "status": "Todo", "assigned_to": self.USER,
			 "reference_doctype": "CRM Deal", "reference_docname": deal.name}
		).insert()
		task.status = status
		task.closing_note = "n"
		task.save()

	def test_clients_are_ranked_by_how_often_they_move_or_drop_activities(self):
		self._task(self.flaky_deal, "Rescheduled")
		self._task(self.flaky_deal, "Canceled")
		self._task(self.flaky_deal, "Done")
		self._task(self.solid_deal, "Done")
		today = frappe.utils.nowdate()
		rows = client_reliability(today, today, user=self.USER)
		self.assertEqual(rows[0]["organization"], "Flaky Mine")
		self.assertEqual((rows[0]["rescheduled"], rows[0]["cancelled"], rows[0]["done"], rows[0]["total"]), (1, 1, 1, 3))
		self.assertEqual(rows[1]["organization"], "Solid Works")
		self.assertEqual(rows[1]["done"], 1)

	def test_the_report_is_the_aggregate(self):
		self._task(self.flaky_deal, "Canceled")
		today = frappe.utils.nowdate()
		report = get_report("client_reliability", today, today, self.USER)
		self.assertEqual(report["rows"], client_reliability(today, today, user=self.USER))
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site run-tests --module crm.tests.test_reports`
Expected: FAIL — `ImportError: cannot import name 'client_reliability'`.

- [ ] **Step 3: Implement**

In `crm/api/dashboard.py`, add after `activity_cancellations`:

```python
def client_reliability(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""Activity outcomes grouped by the client they were for, worst first.

	The one genuinely new idea in the old rep app: which customers move and
	cancel the team's visits. A task reaches its organization through the deal
	it references; a calendar event the same way. Sorted by rescheduled plus
	cancelled so the clients that cost the most time are at the top."""
	Task = DocType("CRM Task")
	Event = DocType("Event")
	Deal = DocType("CRM Deal")
	end = add_days(to_date, 1)

	def flag(column, value):
		return Sum(Case().when(column == value, 1).else_(0))

	tasks = (
		frappe.qb.from_(Task)
		.join(Deal)
		.on((Task.reference_doctype == "CRM Deal") & (Task.reference_docname == Deal.name))
		.where((Task.modified >= from_date) & (Task.modified < end))
		.where(Deal.organization.isnotnull())
		.select(
			Deal.organization.as_("organization"),
			Count(Task.name).as_("total"),
			flag(Task.status, "Done").as_("done"),
			flag(Task.status, "Rescheduled").as_("rescheduled"),
			flag(Task.status, "Canceled").as_("cancelled"),
		)
		.groupby(Deal.organization)
	)
	events = (
		frappe.qb.from_(Event)
		.join(Deal)
		.on((Event.reference_doctype == "CRM Deal") & (Event.reference_docname == Deal.name))
		.where((Event.starts_on >= from_date) & (Event.starts_on < end))
		.where(Deal.organization.isnotnull())
		.select(
			Deal.organization.as_("organization"),
			Count(Event.name).as_("total"),
			(flag(Event.status, "Completed") + flag(Event.status, "Closed")).as_("done"),
			Sum(Case().when(Event.status == "Cancelled", 0).else_(0)).as_("rescheduled"),
			flag(Event.status, "Cancelled").as_("cancelled"),
		)
		.groupby(Deal.organization)
	)
	if user:
		tasks = tasks.where(Task.assigned_to == user)
		events = events.where(Event.owner == user)
	else:
		reps = visible_reps()
		if reps is not None:
			tasks = tasks.where(Task.assigned_to.isin(reps))
			events = events.where(Event.owner.isin(reps))

	merged: dict[str, dict] = {}
	for row in tasks.run(as_dict=True) + events.run(as_dict=True):
		bucket = merged.setdefault(
			row.organization, {"organization": row.organization, "total": 0, "done": 0, "rescheduled": 0, "cancelled": 0}
		)
		for key in ("total", "done", "rescheduled", "cancelled"):
			bucket[key] += int(row.get(key) or 0)
	rows = [frappe._dict(b) for b in merged.values()]
	rows.sort(key=lambda r: (-(r["rescheduled"] + r["cancelled"]), r["organization"]))
	return rows
```

(The events query's `rescheduled` column is a constant zero: an Event has no rescheduled status. It is there so both queries have the same shape.)

In `crm/api/reports.py`, add the consumer and the registry entry:

```python
def _client_reliability(from_date, to_date, user, territory=None):
	from crm.api.dashboard import client_reliability

	return client_reliability(from_date, to_date, user)
```

```python
	"client_reliability": {
		"title": "Client reliability",
		"description": "Activity outcomes by client, most rescheduled and cancelled first",
		"columns": [
			{"key": "organization", "label": "Client", "type": "text"},
			{"key": "total", "label": "Activities", "type": "number"},
			{"key": "done", "label": "Done", "type": "number"},
			{"key": "rescheduled", "label": "Rescheduled", "type": "number"},
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
		],
		"get_rows": _client_reliability,
	},
```

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site run-tests --module crm.tests.test_reports`
Expected: PASS. If `CRM Deal` insert in `setUp` complains about a missing expected deal value, forecasting is enabled on the test site — add `"expected_deal_value": 1, "expected_closure_date": frappe.utils.nowdate()` to both deal fixtures.

- [ ] **Step 5: Check the report and commit**

Open `/crm/reports`, choose **Client reliability**, confirm rows and CSV export. Then:

```bash
git add crm/api/dashboard.py crm/api/reports.py crm/tests/test_reports.py
git commit -m "feat: client reliability report -- which customers move and drop visits"
```

---

### Task 11: A rep lands on the Planner

**Files:**
- Modify: `frontend/src/router.js:230-245`

- [ ] **Step 1: Redirect reps**

In `router.beforeEach`, the `Home` branch currently begins:

```js
  } else if (to.name === 'Home' && isLoggedIn) {
    const { views, getDefaultView } = viewsStore()
    await views.promise
```

Change it to:

```js
  } else if (to.name === 'Home' && isLoggedIn) {
    // Eight of MBP's reps have muscle memory in an app whose home screen is
    // their week. A rep looking for "what am I doing Tuesday" must not have
    // to learn a route on day one; managers keep the views-driven default.
    const { isManager } = usersStore()
    if (!isManager()) {
      next({ name: 'Planner' })
      return
    }
    const { views, getDefaultView } = viewsStore()
    await views.promise
```

`usersStore` is already imported at the top of the file and `users.promise` has already been awaited above this branch.

- [ ] **Step 2: Check in the app and commit**

Log in as a Sales User (not a manager) and open `/crm`: the Planner opens. As a Sales Manager or Administrator: the previous behaviour (default view, or Leads).

```bash
git add frontend/src/router.js
git commit -m "feat: a rep's home is the Planner"
```

---

### Task 12: Docs

**Files:**
- Modify: `.pi/feats/planning/README.md`, `.pi/feats/reporting/README.md`

- [ ] **Step 1: Planning**

In `.pi/feats/planning/README.md`, add `Visit` to the *Matching* table and a paragraph after it:

```markdown
| Visit | `Event` | `starts_on` | `event_category = "Event"`, not `Cancelled` |
```

```markdown
A visit and a meeting are both calendar events; the category is what tells
them apart, and `Meeting` excludes it so one event is emitted under exactly
one kind. The calendar sets no category, so nothing existing changed kind.
`log_unplanned_visit` records a visit that was never planned — a rep called
to site for a breakdown — as an Event in that category plus a plan item
already Done and flagged `manual_override`, in one call.
```

Add to the *Endpoints* table:

```markdown
| `log_unplanned_visit(organization, note, when?, reference?)` | The Event and the fulfilled, overridden item, in one step. A note is required — closing anything without saying why is the habit the old rep app enforced and the one reps notice first |
```

- [ ] **Step 2: Reporting**

In `.pi/feats/reporting/README.md`, change *Five built-ins* to *Six* and add to the list `client reliability`, then append under *Correctness decisions*:

```markdown
- **Cancellations are counted from the records, not the plan.** A cancelled
  task or event fulfils nothing, so the matcher never sees it; `activity_cancellations`
  counts them directly and `plan_adherence` carries the number alongside
  planned/done/missed without changing any of those.
- **Client reliability reaches an organization through the deal an activity
  references.** Sorted by rescheduled + cancelled, worst first.
```

- [ ] **Step 3: Commit**

```bash
git add .pi/feats/planning/README.md .pi/feats/reporting/README.md
git commit -m "docs: visits, unplanned-visit logging, cancellations and client reliability"
```

---

## Self-review

**Spec coverage.** G1 → Tasks 1–2. G2 → Task 6. G3 → Task 3. G4 → Task 4. G5 → Task 10. G6 → Task 8, including the surfaced-not-silent requirement and the null-check probe. G7 → Task 5. G8 → Task 9. G9 → Task 7. Sequencing → task order matches the spec's (model changes 1–4 before surfaces 5–8 before reporting 9–10). *Risks: adoption* → Task 11. *Deliberately not rebuilt* (donuts) → nothing, by design. **Not covered:** migrating the old app's Firestore history — the spec scopes it out.

**Placeholder scan.** Task 8 step 5 says "if `router` is not already defined… add" and Task 5 step 4 says "if `createResource` is not already imported… add" — conditional on file state the implementer can see, with the exact line to add; not a placeholder. Task 3 step 4 is a grep with an exact command and an exact expected outcome.

**Type consistency.** `ACTUAL_SOURCES["Visit"]` (Task 1) is what `log_unplanned_visit` (Task 6) satisfies with `event_category = "Event"` + `status = "Completed"` (Completed is not excluded). `append_to_layout_column(layout, anchor, fieldname) -> bool` is defined in Task 4 and used identically in Task 7. `CLOSED_STATUSES` includes `Rescheduled` from Task 3, and both Tasks 9 and 10 set `closing_note` before closing so Task 4's rule holds in their fixtures. `plan_adherence` rows gain `cancelled` (Task 9) and the report column key matches. `client_reliability` rows use the keys the report columns name (Task 10).
