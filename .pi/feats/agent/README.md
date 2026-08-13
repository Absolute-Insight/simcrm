# Agent Layer

Local-inference features for the CRM. Disabled by default — turn on in
**CRM Agent Settings** after pointing `base_url` at an OpenAI-compatible endpoint.

## Layers

| Module | Responsibility |
|---|---|
| `config.py` | Reads `CRM Agent Settings` into an `AgentConfig` |
| `schemas.py` | Output models; one source for the guided-decoding schema and validation |
| `context.py` | Prompt construction; fences untrusted text as data |
| `client.py` | OpenAI-compatible call, one validation retry, `AgentUnavailable` on failure |
| `tools.py` | The capability layer — permission-checked reads only |
| `api.py` | Whitelisted endpoints; returns `ok` / `disabled` / `unavailable` |
| `install.py` | Idempotent read-only `CRM Agent` role, run from `after_migrate` |

Import direction is one-way: `errors` ← `config`/`schemas`/`context` ← `client` ←
`tools`/`api`. No module imports one to its right.

## Rules

- Reads go through `frappe.get_list`, never `ignore_permissions`.
  `tests/test_tools.py` enforces this by parsing the module's own AST against an
  **allowlist** of the `frappe.*` calls `tools.py` may make, so the invariant cannot
  erode quietly.
  One documented exception: `read_thread` fetches a record's `Communication` rows with
  `frappe.get_all`, gated on a permission-checked read of the parent record first and
  hard-scoped to that parent. frappe's own `permission_query_condition` for
  `Communication` keeps only rows belonging to the reading user's email accounts, so
  `get_list` returned an empty thread for every ordinary CRM user while the endpoint
  still reported `ok`. Authority for a child read comes from its parent — the same
  shape frappe's `get_docinfo` timeline uses. Adding a second exception means adding
  to the allowlist, in review.
- The model is configuration: base URL plus model name. No prompt or parser may be
  model-specific — swapping models must not require a code change.
- Communication bodies are untrusted. They are fenced, the system prompt states that
  fenced text is data rather than instructions, and this layer holds no write tools
  that hostile content could aim at.
- The endpoint degrades: with the flag off or the endpoint down, callers get a status,
  never an exception.

## Running the tests

```bash
cd /workspace/frappe-bench && PYTHONPATH=/workspace bench --site dev.localhost \
  run-tests --app crm --module crm.agent.tests
```

`PYTHONPATH=/workspace` is required in this devcontainer — the bench's `apps/crm` is a
separate checkout, so without it the runner tests that copy rather than the working
tree. No test contacts a model or the network.

## What is not here yet

MCP transport, write-tier tools, the enrichment fallback extractor, and the assistant
tier. Plans live in `docs/superpowers/plans/`.
