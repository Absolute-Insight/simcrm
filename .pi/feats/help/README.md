# In-app help center & the Mentor

> The manual ships with the app, and the Mentor answers from the same files.
> One knowledge source, two surfaces: edit an article and both change in the
> same commit.

## What the user sees

- **Help** in the sidebar footer opens the help center: a dialog with a
  category tree, client-side search (title hits ranked above body hits, with a
  snippet), and articles rendered in-app. Nothing is hosted elsewhere; it
  works offline and is versioned with the code it documents.
- **Mentor** is a box above the search field in the help center. It answers
  questions about the product, grounded on the help articles, and cites the
  ones it used as chips that deep-link into the help center. Sending a
  question switches the right pane to the transcript; a chip or a tree click
  switches back and keeps it.
- **Assistant** in the sidebar (the slide-out panel, same pattern as
  Suggestions) is a different surface with a different knowledge source: the
  admin-curated `CRM Knowledge Article` records from **Settings → Knowledge**,
  optionally the product catalogue. **Analyst** is a third, admin-only page
  over the metrics layer. Both are described in
  `docs/superpowers/specs/2026-09-01-ai-surfaces-design.md`; the help center
  article for each is under the **AI & automation** category.

## Content

`crm/help/articles/*.md` — markdown with a small frontmatter block
(`title`, `category`, `order`). Categories and their display order live in
`crm/help/__init__.py::CATEGORY_ORDER`; the loader *refuses* a malformed file
(missing key, unknown category, empty body) so a bad edit fails
`crm/tests/test_help.py` instead of silently vanishing from both surfaces.

`crm.api.help.get_articles` returns the whole set — a few tens of kilobytes —
and the client searches locally; there is deliberately no per-article endpoint
and no server-side search.

## The mentor tier

`crm.agent.api.ask_mentor(question, history)` — the model-tier endpoint
behind the help center box (it was `ask_assistant` until the Assistant moved
to the knowledge base), built on the same skeleton as
`summarise_thread`/`draft_reply`: per-user rate limit, daily budget,
`disabled`/`unavailable` degrade statuses, guided decoding into
`AssistantAnswer`.

What makes this tier different from the thread tiers:

- **No CRM reads at all.** Its whole knowledge is the shipped manual, so
  there is no record or email for hostile content to inject through, and no
  answer can leak anything the help center does not already show every user.
- **Grounding is deterministic.** `crm/agent/knowledge.py` (pure, frappe-free,
  in the layering map like `context`) scores articles against the question —
  title hits over body hits, frequency capped — and quotes the top few in the
  system message. When nothing scores, the prompt tells the model to say so
  rather than improvise.
- **Citations are filtered.** The model names `related_articles`; the endpoint
  drops any name not in the real catalogue, so an invented citation cannot
  become a dead link.
- **Output is plain text.** The panel renders answers with `{{ }}`, never
  `v-html` — the standing rule that model output is untrusted input.

History is the client's own transcript (in-memory only, per session); the
server keeps only the last turns, drops malformed entries, and caps lengths.

## Rendering rule

Article markdown → `marked` → the house `sanitizeHTML` → `v-html`, all in
`HelpCenterModal.vue`. `renderArticleMarkdown` in `utils/helpCenter.js` is
deliberately unsanitized and says so — DOMPurify does not function under
happy-dom, so sanitization lives at the component like every other HTML path.

## Key files

| File | Role |
|---|---|
| `crm/help/__init__.py` | Loader + frontmatter contract; imports no frappe |
| `crm/help/articles/` | The manual, one markdown file per article |
| `crm/api/help.py` | `get_articles` endpoint |
| `crm/agent/knowledge.py` | Pure grounding: selection scoring + prompt building |
| `crm/agent/api.py::ask_mentor` | The Mentor endpoint |
| `frontend/src/stores/help.js` | Modal visibility, article deep-link, content resource |
| `frontend/src/stores/mentor.js` | Mentor transcript, ask/retry |
| `frontend/src/components/Modals/HelpCenterModal.vue` | The help center dialog, with the Mentor block |
| `frontend/src/components/AgentChat.vue` | The shared transcript/input component the three surfaces render |
| `frontend/src/utils/helpCenter.js` | Pure search/group/render helpers (unit-tested) |
