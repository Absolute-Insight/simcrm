# In-app help center & assistant chat

> The manual ships with the app, and the assistant answers from the same
> files. One knowledge source, two surfaces: edit an article and both change
> in the same commit.

## What the user sees

- **Help** in the sidebar footer opens the help center: a dialog with a
  category tree, client-side search (title hits ranked above body hits, with a
  snippet), and articles rendered in-app. Nothing is hosted elsewhere; it
  works offline and is versioned with the code it documents.
- **Assistant** in the sidebar opens a slide-out chat panel (desktop shell,
  same pattern as Suggestions). It answers questions about the product,
  grounded on the help articles, and cites the ones it used as chips that
  deep-link into the help center.

## Content

`crm/help/articles/*.md` — markdown with a small frontmatter block
(`title`, `category`, `order`). Categories and their display order live in
`crm/help/__init__.py::CATEGORY_ORDER`; the loader *refuses* a malformed file
(missing key, unknown category, empty body) so a bad edit fails
`crm/tests/test_help.py` instead of silently vanishing from both surfaces.

`crm.api.help.get_articles` returns the whole set — a few tens of kilobytes —
and the client searches locally; there is deliberately no per-article endpoint
and no server-side search.

## The assistant tier

`crm.agent.api.ask_assistant(question, history)` — the third model-tier
endpoint, built on the same skeleton as `summarise_thread`/`draft_reply`:
per-user rate limit, daily budget, `disabled`/`unavailable` degrade statuses,
guided decoding into `AssistantAnswer`.

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
| `crm/agent/api.py::ask_assistant` | The chat endpoint |
| `frontend/src/stores/help.js` | Modal visibility, article deep-link, content resource |
| `frontend/src/stores/assistant.js` | Panel state, transcript, ask/retry |
| `frontend/src/components/Modals/HelpCenterModal.vue` | The help center dialog |
| `frontend/src/components/Assistant.vue` | The chat panel |
| `frontend/src/utils/helpCenter.js` | Pure search/group/render helpers (unit-tested) |
